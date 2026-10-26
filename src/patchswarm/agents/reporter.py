"""Reporter agent - compiles the structured JSON + Markdown mission report."""
from __future__ import annotations

import asyncio

from ..messages import REPORT_DONE, REPORT_REQUEST
from ..report import build_report, render_markdown
from .base import AgentError, BaseAgent


class ReporterAgent(BaseAgent):
    """Stage 4: audit trail + metrics.

    Receives every artifact the swarm produced (or the partial set, when
    operating in degraded/failover mode) and emits ``reporter.report_done``
    with a fully structured JSON report and a human-readable Markdown
    rendering.
    """

    name = "reporter"
    subscriptions = (REPORT_REQUEST,)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.last_report: dict | None = None

    async def handle(self, envelope) -> None:
        payload = envelope.payload
        if "artifacts" not in payload:
            raise AgentError("reporter received a request without artifacts")
        report = build_report(
            mission_id=envelope.correlation_id,
            status=payload.get("status", "ok"),
            artifacts=payload["artifacts"],
            errors=payload.get("errors", []),
            bus_metrics=dict(payload.get("bus_metrics", {})),
            started_at=payload.get("started_at"),
        )
        markdown = render_markdown(report)
        self.last_report = report
        await asyncio.sleep(0)
        await self.reply(
            envelope,
            REPORT_DONE,
            {"report": report, "markdown": markdown},
        )
