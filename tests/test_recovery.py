"""Level-1 (agent retries) and level-2 (mission failover) recovery tests."""
import asyncio

import pytest

from patchswarm import MissionRunner
from patchswarm.agents import (
    AnalyzerAgent,
    BaseAgent,
    Orchestrator,
    ReconAgent,
    ReporterAgent,
)
from patchswarm.bus import EventBus
from patchswarm.messages import (
    AGENT_FAILED,
    ANALYZE_REQUEST,
    INTENT,
    RECON_REQUEST,
    REPORT_REQUEST,
    Envelope,
)


class FlakyAgent(BaseAgent):
    """Fails its first N handles with a recoverable error, then succeeds."""

    name = "flaky"
    subscriptions = ("test.ping",)

    def __init__(self, bus, fails=1, **kwargs):
        super().__init__(bus, **kwargs)
        self.fails = fails
        self.succeeded = []

    async def handle(self, envelope):
        if self.fails > 0:
            self.fails -= 1
            raise RuntimeError("transient failure")
        self.succeeded.append(envelope)


class HopelessAgent(FlakyAgent):
    name = "hopeless"

    def __init__(self, bus, **kwargs):
        super().__init__(bus, fails=10_000, **kwargs)


async def test_agent_retries_transient_failure_then_succeeds(bus):
    flaky = FlakyAgent(bus, fails=2, max_retries=3, backoff=0)
    await bus.publish(Envelope("test.ping", {"n": 1}, "unit", "c1"))
    assert flaky.handled == 1
    assert flaky.total_failures == 2  # two failed attempts before success
    assert flaky.failed_envelopes == []


async def test_agent_signals_agent_failed_when_retries_exhausted(bus):
    failed_msgs = []

    async def recorder(env):
        failed_msgs.append(env)

    bus.subscribe(AGENT_FAILED, recorder)
    hopeless = HopelessAgent(bus, max_retries=2, backoff=0)
    delivered = await bus.publish(Envelope("test.ping", {"n": 1}, "unit", "c1"))
    assert delivered == 1  # receive() returns normally, never raises
    assert hopeless.attempted == 3  # 1 + 2 retries
    assert hopeless.handled == 0
    assert len(failed_msgs) == 1
    assert failed_msgs[0].payload["agent"] == "hopeless"
    assert failed_msgs[0].correlation_id == "c1"
    assert "transient failure" in failed_msgs[0].payload["error"]


async def test_agent_failure_path_keeps_bus_metrics_clean(bus):
    """Exhausted retries become an AGENT_FAILED message, not a bus error."""
    hopeless = HopelessAgent(bus, max_retries=2, backoff=0)
    await bus.publish(Envelope("test.ping", {}, "unit", "c1"))
    # the ping itself + the structured failure signal
    assert bus.metrics["messages_published"] == 2
    # receive() absorbs the failure: the bus never saw a raw exception
    assert bus.metrics["delivery_errors"] == 0
    assert bus.metrics["deliveries"] == 1  # nobody subscribes to AGENT_FAILED here


async def test_mission_failover_on_permanent_stage_failure(requirements):
    """Recon dies permanently -> orchestrator reroutes to a degraded report."""
    runner = MissionRunner(agent_retries=1, agent_backoff=0)
    # Sabotage recon: replace its handler content so it always raises.
    async def always_broken(env):
        raise RuntimeError("recon exploded")

    runner.recon.handle = always_broken
    report = await runner.run({"manifest_content": requirements}, timeout=10.0)
    assert report["status"] == "degraded"
    assert report["metrics"]["stages_completed"] == []
    assert any("recon failed" in e for e in report["errors"])
    assert report["metrics"]["packages_scanned"] == 0


async def test_mission_fallback_report_when_reporter_is_down(requirements):
    """Even the reporter dying still yields a structured report."""
    runner = MissionRunner()

    async def dead_reporter(env):
        raise RuntimeError("reporter exploded")

    runner.reporter.handle = dead_reporter
    report = await runner.run({"manifest_content": requirements}, timeout=10.0)
    assert report["status"] == "failed"
    assert "reporter failed" in " ".join(report["errors"])
    assert report["metrics"]["vulnerabilities_found"] == 5
    assert report["patch_plan"], "fallback report keeps partial artifacts"
    assert "markdown" in report


async def test_mission_timeout_yields_structured_report(requirements):
    """A wedged stage agent cannot stall the mission past its timeout."""

    class WedgedRecon(ReconAgent):
        async def handle(self, envelope):
            await asyncio.sleep(999)

    runner = MissionRunner()
    wedged = WedgedRecon(runner.bus, max_retries=0)
    # replace the healthy recon subscriber with the wedged one
    assert runner.bus.unsubscribe(RECON_REQUEST, runner.recon.receive)
    report = await runner.run({"manifest_content": requirements}, timeout=0.15)
    assert report["status"] == "failed"
    assert any("timeout" in e for e in report["errors"])
    assert set(report["metrics"]["by_severity"]) == {"critical", "high", "medium", "low"}
    # structured shape is identical to a happy-path report
    for key in ("mission_id", "status", "metrics", "findings", "errors"):
        assert key in report


async def test_invalid_intent_is_rejected_but_reported(clean_requirements):
    runner = MissionRunner()
    report = await runner.run({"manifest_content": ""}, timeout=10.0)
    assert report["status"] == "degraded"
    assert any("empty" in e.lower() for e in report["errors"])


async def test_unparseable_manifest_degrades_instead_of_crashing():
    runner = MissionRunner()
    report = await runner.run(
        {"manifest_content": "{ definitely not json", "filename": "package.json"},
        timeout=10.0,
    )
    assert report["status"] == "degraded"
    assert report["errors"]
    assert report["metrics"]["vulnerabilities_found"] == 0
