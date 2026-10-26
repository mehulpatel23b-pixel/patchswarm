"""Orchestrator - the coordinator of the swarm.

Parses mission intent into a concrete plan, delegates each phase over
the bus, tracks artifacts per correlation id, and drives level-2
(mission-level) failover: when a stage agent exhausts its retries, the
orchestrator reroutes the mission to the Reporter in degraded mode so
the mission still ends with a structured report.
"""
from __future__ import annotations

import time

from ..messages import (
    AGENT_FAILED,
    ANALYZE_REQUEST,
    ENGINEER_REQUEST,
    INVENTORY,
    INTENT,
    PATCH_RESULT,
    RECON_REQUEST,
    REPORT_DONE,
    REPORT_REQUEST,
    VERDICTS,
)
from ..report import build_report, render_markdown
from .base import AgentError, BaseAgent

STAGE_ORDER = ("inventory", "analysis", "patch")
STAGE_TOPICS = {INVENTORY: "inventory", VERDICTS: "analysis", PATCH_RESULT: "patch"}

class Orchestrator(BaseAgent):
    """Manager agent: intent parsing, delegation, failover."""

    name = "orchestrator"
    subscriptions = (
        INTENT,
        INVENTORY,
        VERDICTS,
        PATCH_RESULT,
        REPORT_DONE,
        AGENT_FAILED,
    )

    def __init__(self, bus, completer=None, **kwargs) -> None:
        super().__init__(bus, **kwargs)
        self.missions: dict[str, dict] = {}
        self._completer = completer

    # -- mission lifecycle -------------------------------------------------

    def mission(self, correlation_id: str) -> dict:
        return self.missions.setdefault(
            correlation_id,
            {
                "id": correlation_id,
                "status": "planning",
                "started_at": time.time(),
                "artifacts": {},
                "events": [],
                "errors": [],
            },
        )

    def _record(self, mission: dict, event: str, detail: str = "") -> None:
        mission["events"].append({"event": event, "detail": detail, "ts": time.time()})

    def _complete(self, mission: dict, report: dict) -> None:
        mission["status"] = report["status"]
        mission["report"] = report
        if self._completer:
            self._completer(mission["id"], report)

    # -- routing -----------------------------------------------------------

    async def handle(self, envelope) -> None:
        topic = envelope.topic
        if topic == INTENT:
            await self._on_intent(envelope)
        elif topic in STAGE_TOPICS:
            await self._on_stage_result(envelope, topic)
        elif topic == REPORT_DONE:
            self._on_report(envelope)
        elif topic == AGENT_FAILED:
            await self._on_agent_failed(envelope)

    # -- handlers ----------------------------------------------------------

    async def _on_intent(self, envelope) -> None:
        """Parse raw mission intent into a concrete first step."""
        mission = self.mission(envelope.correlation_id)
        request = dict(envelope.payload or {})
        filename = request.get("filename") or "requirements.txt"
        content = request.get("manifest_content")
        if not content and request.get("manifest_path"):
            try:
                with open(request["manifest_path"], encoding="utf-8") as fh:
                    content = fh.read()
            except OSError as exc:
                await self._failover(
                    mission, envelope, reason=f"intent rejected: unreadable manifest ({exc})"
                )
                return
        if not content or not content.strip():
            await self._failover(
                mission, envelope, reason="intent rejected: manifest content is empty"
            )
            return
        mission["status"] = "running"
        mission["options"] = {
            "filename": filename,
            "dry_run": bool(request.get("dry_run", False)),
        }
        self._record(mission, "intent_parsed", f"manifest={filename}")
        await self.reply(
            envelope,
            RECON_REQUEST,
            {"manifest_content": content, "filename": filename},
        )

    async def _on_stage_result(self, envelope, topic) -> None:
        mission = self.mission(envelope.correlation_id)
        stage = STAGE_TOPICS[topic]
        mission["artifacts"][stage] = envelope.payload
        self._record(mission, f"{stage}_collected")
        if stage == "inventory":
            await self.reply(
                envelope,
                ANALYZE_REQUEST,
                {"inventory": envelope.payload},
            )
        elif stage == "analysis":
            await self.reply(
                envelope,
                ENGINEER_REQUEST,
                {
                    "inventory": mission["artifacts"]["inventory"],
                    "verdicts": envelope.payload.get("verdicts", []),
                    "dry_run": mission.get("options", {}).get("dry_run", False),
                },
            )
        elif stage == "patch":
            mission["report_requested"] = True
            await self._request_report(mission, envelope, status="ok")

    async def _request_report(self, mission, envelope, status: str) -> None:
        self._record(mission, "report_requested", f"status={status}")
        await self.reply(
            envelope,
            REPORT_REQUEST,
            {
                "artifacts": mission["artifacts"],
                "status": status,
                "errors": mission["errors"],
                "bus_metrics": dict(self.bus.metrics),
                "started_at": mission["started_at"],
            },
        )

    def _on_report(self, envelope) -> None:
        mission = self.mission(envelope.correlation_id)
        report = envelope.payload.get("report")
        if report and not report.get("markdown"):
            report["markdown"] = envelope.payload.get("markdown", "")
        if not report:
            mission["errors"].append("reporter returned no report payload")
            report = self._fallback_report(mission, reason="empty reporter payload")
        self._record(mission, "report_delivered")
        self._complete(mission, report)

    async def _on_agent_failed(self, envelope) -> None:
        """Level-2 recovery: a stage agent exhausted its retries."""
        mission = self.mission(envelope.correlation_id)
        agent = envelope.payload.get("agent", "unknown")
        error = envelope.payload.get("error", "unknown error")
        failed_topic = envelope.payload.get("failed_topic")
        self._record(mission, "agent_failed", f"{agent}: {error}")

        if agent == "reporter":
            # The reporter itself is down - synthesize the structured report
            # directly so the mission still completes with an artifact.
            mission["errors"].append(f"reporter failed: {error}")
            report = self._fallback_report(mission, reason=error)
            self._complete(mission, report)
            return

        mission["errors"].append(f"{agent} failed after retries: {error}")
        await self._failover(
            mission, envelope, reason=f"stage agent '{agent}' failed: {error}"
        )

    async def _failover(self, mission, envelope, reason: str) -> None:
        """Reroute whatever the mission has to the reporter in degraded mode."""
        if mission.get("report_requested"):
            # Failover already in flight; just note the extra error.
            mission["errors"].append(reason)
            return
        mission["report_requested"] = True
        mission["status"] = "degraded"
        mission.setdefault("errors", []).append(reason)
        self._record(mission, "failover", reason)
        await self.reply(
            envelope,
            REPORT_REQUEST,
            {
                "artifacts": mission["artifacts"],
                "status": "degraded",
                "errors": mission["errors"],
                "bus_metrics": dict(self.bus.metrics),
                "started_at": mission["started_at"],
            },
        )

    @staticmethod
    def _fallback_report(mission: dict, reason: str) -> dict:
        """Absolute last resort: a structured report without the reporter."""
        report = build_report(
            mission_id=mission["id"],
            status="failed",
            artifacts=mission.get("artifacts", {}),
            errors=mission.get("errors", []) + [f"fallback report: {reason}"],
            bus_metrics={},
            started_at=mission.get("started_at"),
        )
        report["markdown"] = render_markdown(report)
        return report
