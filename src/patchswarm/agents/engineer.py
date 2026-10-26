"""Engineer agent - patch generation and the validation gate."""
from __future__ import annotations

import asyncio

from ..manifest import Dependency, parse_manifest, to_requirements_text
from ..messages import ENGINEER_REQUEST, PATCH_RESULT
from .base import AgentError, BaseAgent

# Order used when merging multiple advisories for the same package:
# the most severe advisory governs the patch action.
_SEVERITY_ORDER = ["low", "medium", "high", "critical"]


class EngineerAgent(BaseAgent):
    """Stage 3: turn verdicts into a patch plan, apply it, and validate.

    The patch strategy is minimal-blast-radius: only touch packages that
    have an active finding, upgrading straight to the advisory's
    ``fixed_in`` version (which also floors unpinned floats). Everything
    else in the manifest is carried through untouched.

    Validation gate (simulated CI, zero runtime deps):
      1. upgrades_sufficient - every patched package sits at its fixed_in
      2. artifact_integrity - no package was silently dropped or added
      3. explicit_pinning - the patched manifest pins an exact version
    The gate must pass for ``validation_passed``; failed checks are
    reported so the Reporter can surface them.
    """

    name = "engineer"
    subscriptions = (ENGINEER_REQUEST,)

    async def handle(self, envelope) -> None:
        payload = envelope.payload
        verdicts = payload.get("verdicts") or []
        inventory = payload.get("inventory") or {}
        dry_run = bool(payload.get("dry_run", False))

        if "packages" not in inventory:
            raise AgentError("engineer requires the inventory artifacts")

        plan = self.plan_patches(verdicts)
        patched_content = (
            ""
            if dry_run
            else self.apply_patches(
                inventory.get("filename", "requirements.txt"),
                inventory["packages"],
                plan,
            )
        )
        checks = self.validate(inventory["packages"], plan, patched_content, dry_run)
        await asyncio.sleep(0)  # yield, simulating a CI step
        await self.reply(
            envelope,
            PATCH_RESULT,
            {
                "patch_plan": plan,
                "patched_manifest": patched_content,
                "patched_count": len(plan),
                "dry_run": dry_run,
                "checks": checks,
                "validation_passed": all(c["passed"] for c in checks),
            },
        )

    @staticmethod
    def plan_patches(verdicts: list[dict]) -> list[dict]:
        """One upgrade action per package, deduped across advisories.

        A package with several findings gets a single coherent action
        governed by its most severe advisory.
        """
        targets: dict[str, dict] = {}
        for verdict in verdicts:
            name = verdict["package"]
            existing = targets.get(name)
            if existing is None:
                targets[name] = {
                    "package": name,
                    "installed": verdict["installed"],
                    "target": verdict["fixed_in"],
                    "advisory_ids": [verdict["advisory_id"]],
                    "severity": verdict["severity"],
                    "risk": verdict["risk"],
                    "action": "upgrade" if verdict["installed"] else "pin",
                }
            else:
                existing["advisory_ids"].append(verdict["advisory_id"])
                if _SEVERITY_ORDER.index(verdict["severity"]) > _SEVERITY_ORDER.index(
                    existing["severity"]
                ):
                    existing["severity"] = verdict["severity"]
                    existing["risk"] = verdict["risk"]
        return sorted(targets.values(), key=lambda step: (-step["risk"], step["package"]))

    @staticmethod
    def apply_patches(
        filename: str, packages: list[dict], plan: list[dict]
    ) -> str:
        """Rewrite the manifest with pinned safe versions for hit packages.

        The patched artifact is always a fully-pinned requirements.txt -
        the smallest contract every downstream tooling understands.
        """
        upgrades = {step["package"]: step["target"] for step in plan}
        rendered = [
            Dependency(
                name=dep["name"],
                version=upgrades.get(dep["name"], dep.get("version") or "0.0.0"),
                source=filename,
            )
            for dep in packages
        ]
        return to_requirements_text(rendered)

    @staticmethod
    def validate(
        packages: list[dict], plan: list[dict], patched_content: str, dry_run: bool
    ) -> list[dict]:
        checks = [
            {
                "name": "upgrades_sufficient",
                "passed": True,
                "detail": "every patched package reaches its fixed_in floor",
            }
        ]
        if dry_run:
            checks[0]["passed"] = False
            checks[0]["detail"] = "dry-run mission: no artifact produced"
            checks.append(
                {
                    "name": "dry_run",
                    "passed": True,
                    "detail": "patch plan built but not applied",
                }
            )
            return checks

        parsed = parse_manifest(patched_content, "requirements.txt")
        by_name = {d.name: d.version for d in parsed}
        upgrades_sufficient = all(
            by_name.get(step["package"]) == step["target"] for step in plan
        )
        integrity = set(by_name) == {dep["name"] for dep in packages}
        pinned = all(by_name.values())
        checks[0]["passed"] = upgrades_sufficient
        checks.extend(
            [
                {
                    "name": "artifact_integrity",
                    "passed": integrity,
                    "detail": f"{len(by_name)}/{len(packages)} packages carried through",
                },
                {
                    "name": "explicit_pinning",
                    "passed": pinned,
                    "detail": "patched manifest pins an exact version per package",
                },
            ]
        )
        return checks
