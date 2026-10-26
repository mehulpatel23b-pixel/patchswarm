"""Deterministic report building + Markdown rendering for mission reports."""
from __future__ import annotations

import time

from .advisories import WEIGHTS  # noqa: F401  (kept for downstream consumers)

_SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def build_report(
    mission_id: str,
    status: str,
    artifacts: dict,
    errors: list,
    bus_metrics: dict,
    started_at: float | None,
) -> dict:
    """Assemble the structured mission report.

    Never raises: any missing artifact degrades gracefully into zeroed
    metrics while the error list explains why - a partial report still
    always parses.
    """
    inventory = artifacts.get("inventory") or {}
    verdicts_artifact = artifacts.get("analysis") or {}
    verdicts = verdicts_artifact.get("verdicts", [])
    patch = artifacts.get("patch") or {}
    checks = patch.get("checks", [])

    by_severity = verdicts_artifact.get("by_severity") or {
        s: sum(1 for v in verdicts if v.get("severity") == s)
        for s in _SEVERITY_ORDER
    }

    completed_stages = [k for k in ("inventory", "analysis", "patch") if k in artifacts]
    return {
        "mission_id": mission_id,
        "status": status,
        "generated_at": time.time(),
        "duration_ms": int((time.time() - started_at) * 1000) if started_at else -1,
        "manifest": inventory.get("filename"),
        "metrics": {
            "packages_scanned": inventory.get("scanned_count", 0),
            "unpinned_packages": inventory.get("unpinned_count", 0),
            "vulnerabilities_found": len(verdicts),
            "by_severity": by_severity,
            "aggregated_risk": verdicts_artifact.get("risk_score", 0),
            "patches_proposed": patch.get("patched_count", 0),
            "validation_passed": patch.get("validation_passed", False),
            "stages_completed": completed_stages,
            "agent_errors": len(errors),
        },
        "findings": verdicts,
        "patch_plan": patch.get("patch_plan", []),
        "patched_manifest": patch.get("patched_manifest", ""),
        "validation_checks": checks,
        "errors": errors,
        "bus_metrics": bus_metrics,
    }


def render_markdown(report: dict) -> str:
    """Render the JSON report as a compact Markdown audit document."""
    metrics = report["metrics"]
    sev = metrics["by_severity"]
    duration = max(report["duration_ms"], 0)
    lines = [
        "# Patchswarm Security Mission Report",
        "",
        f"* **Mission**: `{report['mission_id']}`",
        f"* **Status**: `{report['status']}`",
        f"* **Manifest**: `{report.get('manifest') or 'n/a'}`",
        f"* **Duration**: {duration} ms",
        "",
        "## Headline metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Packages scanned | {metrics['packages_scanned']} |",
        f"| Vulnerabilities found | {metrics['vulnerabilities_found']} "
        f"({sev.get('critical', 0)} critical / {sev.get('high', 0)} high / "
        f"{sev.get('medium', 0)} medium / {sev.get('low', 0)} low) |",
        f"| Aggregated risk | {metrics['aggregated_risk']}/100 |",
        f"| Patches proposed | {metrics['patches_proposed']} |",
        f"| Validation gate | {'PASSED' if metrics['validation_passed'] else 'FAILED'} |",
        f"| Agent errors observed | {metrics['agent_errors']} |",
        "",
    ]
    if report["findings"]:
        lines += [
            "## Findings",
            "",
            "| Package | Installed | Advisory | Severity | Fix |",
            "| --- | --- | --- | --- | --- |",
        ]
        for finding in report["findings"]:
            lines.append(
                f"| {finding['package']} | {finding['installed'] or 'unpinned'} | "
                f"{finding['advisory_id']} | {finding['severity']} | {finding['fixed_in']} |"
            )
        lines.append("")
    if report["patch_plan"]:
        lines += [
            "## Patch plan",
            "",
            "| Package | Action | Installed | Target | Advisories |",
            "| --- | --- | --- | --- | --- |",
        ]
        for step in report["patch_plan"]:
            lines.append(
                f"| {step['package']} | {step['action']} | {step['installed'] or 'unpinned'} | "
                f"{step['target']} | {', '.join(step['advisory_ids'])} |"
            )
        lines.append("")
    if report["validation_checks"]:
        lines += ["## Validation gate", ""]
        for check in report["validation_checks"]:
            mark = "PASS" if check["passed"] else "FAIL"
            lines.append(f"- **{check['name']}**: {mark} - {check['detail']}")
        lines.append("")
    if report.get("patched_manifest"):
        lines += [
            "## Patched manifest",
            "",
            "```",
            report["patched_manifest"].rstrip(),
            "```",
            "",
        ]
    if report["errors"]:
        lines += ["## Errors & degraded stages", ""]
        for err in report["errors"]:
            lines.append(f"- `{err}`")
        lines.append("")
    return "\n".join(lines)
