"""MissionRunner - operational harness with level-2 recovery.

Guarantees, in order:
 1. Envelope-published intent -> the swarm executes autonomously.
 2. Any awaitable result blocks at most ``timeout`` seconds.
 3. No matter what fails - stage agents, the reporter, the entire swarm -
    ``run()`` always returns the same *structured* report shape.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

from .agents import AnalyzerAgent, EngineerAgent, Orchestrator, ReconAgent, ReporterAgent
from .bus import EventBus
from .messages import INTENT, Envelope
from .report import build_report, render_markdown


class MissionRunner:
    """Builds a swarm on one bus and runs vulnerability-response missions."""

    def __init__(self, agent_retries: int = 2, agent_backoff: float = 0.005) -> None:
        self.bus = EventBus()
        self._futures: dict[str, asyncio.Future] = {}
        self.agent_retries = agent_retries
        self.agent_backoff = agent_backoff
        self.orchestrator = Orchestrator(self.bus, completer=self._complete, max_retries=agent_retries, backoff=agent_backoff)
        self.recon = ReconAgent(self.bus, max_retries=agent_retries, backoff=agent_backoff)
        self.analyzer = AnalyzerAgent(self.bus, max_retries=agent_retries, backoff=agent_backoff)
        self.engineer = EngineerAgent(self.bus, max_retries=agent_retries, backoff=agent_backoff)
        self.reporter = ReporterAgent(self.bus, max_retries=agent_retries, backoff=agent_backoff)

    # -- completion plumbing -------------------------------------------------

    def _complete(self, mission_id: str, report: dict) -> None:
        future = self._futures.get(mission_id)
        if future is not None and not future.done():
            future.set_result(report)

    # -- public API ------------------------------------------------------------

    async def run(
        self,
        mission_input: dict,
        timeout: float = 15.0,
        mission_id: str | None = None,
    ) -> dict:
        """Execute one mission and always return a structured report.

        ``mission_input`` = {"manifest_content" | "manifest_path",
        "filename"?, "dry_run"?} - the raw intent; the Orchestrator
        parses it.
        """
        loop = asyncio.get_running_loop()
        correlation_id = mission_id or uuid.uuid4().hex[:12]
        future = loop.create_future()
        self._futures[correlation_id] = future
        # Fire intent delivery as its own task: a wedged subscriber must
        # never prevent the mission timeout from firing.
        publish_task = asyncio.create_task(
            self.bus.publish(
                Envelope(
                    topic=INTENT,
                    payload=dict(mission_input or {}),
                    sender="mission-runner",
                    correlation_id=correlation_id,
                )
            )
        )
        try:
            try:
                report = await asyncio.wait_for(future, timeout)
            except asyncio.TimeoutError:
                report = self._timeout_report(
                    correlation_id, mission_input, timeout
                )
            # The future resolving (or the timeout firing) takes
            # precedence over any still-running delivery work: a wedged
            # subscriber must never stall mission completion.
            publish_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await publish_task
            return report
        finally:
            self._futures.pop(correlation_id, None)

    def run_sync(self, mission_input: dict, timeout: float = 15.0) -> dict:
        """Synchronous convenience wrapper around :meth:`run`."""
        return asyncio.run(self.run(mission_input, timeout=timeout))

    # -- level-2 fallback ------------------------------------------------------

    def _timeout_report(
        self,
        correlation_id: str,
        mission_input: dict,
        timeout: float,
    ) -> dict:
        mission = self.orchestrator.missions.get(correlation_id) or {}
        artifacts = mission.get("artifacts", {})
        partial_errors = list(mission.get("errors", []))
        report = build_report(
            mission_id=correlation_id,
            status="failed",
            artifacts=artifacts,
            errors=partial_errors
            + [
                f"mission timed out after {timeout}s: failover engaged, "
                "partial artifacts preserved"
            ],
            bus_metrics=dict(self.bus.metrics),
            started_at=None,
        )
        report["errors"].append(f"timeout_budget_exceeded: {timeout}s")
        report["markdown"] = render_markdown(report)
        return report
