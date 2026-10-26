"""Analyzer agent - offline advisory correlation + risk triage."""
from __future__ import annotations

import asyncio

from ..advisories import WEIGHTS, advisories_for, max_severity
from ..manifest import is_affected
from ..messages import ANALYZE_REQUEST, VERDICTS
from .base import AgentError, BaseAgent


class AnalyzerAgent(BaseAgent):
    """Stage 2: correlate inventory against the advisory database.

    Produces one verdict per (package, advisory) hit with a 0-100 risk
    score, then emits ``analyzer.verdicts`` with the triaged findings
    sorted most-severe-first.
    """

    name = "analyzer"
    subscriptions = (ANALYZE_REQUEST,)

    async def handle(self, envelope) -> None:
        inventory = envelope.payload.get("inventory")
        if not inventory or "packages" not in inventory:
            raise AgentError("analyzer received an inventory without packages")

        verdicts = self.triage(inventory["packages"])
        await asyncio.sleep(0)
        await self.reply(
            envelope,
            VERDICTS,
            {
                "verdicts": verdicts,
                "by_severity": count_by_severity(verdicts),
                "risk_score": risk_score(verdicts),
                "top_severity": max_severity((v["severity"] for v in verdicts),)
                if verdicts
                else "none",
            },
        )

    @staticmethod
    def triage(packages: list[dict]) -> list[dict]:
        verdicts = []
        for dep in packages:
            for advisory in advisories_for(dep["name"]):
                if is_affected(dep.get("version"), advisory["affected"]):
                    verdicts.append(
                        {
                            "package": dep["name"],
                            "installed": dep.get("version"),
                            "unpinned": dep.get("version") is None,
                            "advisory_id": advisory["id"],
                            "severity": advisory["severity"],
                            "summary": advisory["summary"],
                            "fixed_in": advisory["fixed_in"],
                            "affected_spec": advisory["affected"],
                            "risk": WEIGHTS[advisory["severity"]],
                        }
                    )
        return sorted(
            verdicts, key=lambda v: (-v["risk"], v["package"], v["advisory_id"])
        )


def count_by_severity(verdicts: list[dict]) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for verdict in verdicts:
        counts[verdict["severity"]] = counts.get(verdict["severity"], 0) + 1
    return counts


def risk_score(verdicts: list[dict]) -> int:
    """Composite 0-100 mission risk: mean severity weight, floored with a
    criticality bonus when any critical finding exists."""
    if not verdicts:
        return 0
    mean = sum(v["risk"] for v in verdicts) / len(verdicts)
    bonus = 15 if any(v["severity"] == "critical" for v in verdicts) else 0
    return int(min(100, mean + bonus))
