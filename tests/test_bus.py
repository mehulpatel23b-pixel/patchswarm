"""Concurrency + envelope plumbing of the event bus."""
import pytest

from patchswarm.messages import AGENT_FAILED, Envelope


def _mk(sink):
    async def handler(env):
        sink.append(env)

    return handler


async def test_publish_delivers_to_subscriber(bus):
    seen = []
    bus.subscribe("demo.topic", _mk(seen))
    env = Envelope(topic="demo.topic", payload={"k": 1}, sender="t", correlation_id="c1")
    delivered = await bus.publish(env)
    assert delivered == 1
    assert seen and seen[0].payload == {"k": 1}


async def test_publish_multiple_subscribers_all_receive(bus):
    seen_a, seen_b = [], []
    bus.subscribe("fanout", _mk(seen_a))
    bus.subscribe("fanout", _mk(seen_b))
    await bus.publish(Envelope("fanout", {}, "t", "c1"))
    assert len(seen_a) == 1 and len(seen_b) == 1


async def test_correlation_id_preserved_across_bus(bus):
    captured = []
    bus.subscribe("mk.topic", _mk(captured))
    origin = Envelope("mk.topic", {"x": True}, "unit-test", correlation_id="corr-42")
    await bus.publish(origin)
    assert captured[0].correlation_id == "corr-42"
    follow_up = captured[0].with_payload("other.topic", {"y": 1})
    assert follow_up.correlation_id == "corr-42"
    assert follow_up.sender == "unit-test"


async def test_handler_exception_recorded_never_raises(bus):
    async def broken(env):
        raise RuntimeError("boom")

    ok_seen = []
    bus.subscribe("risky", broken)
    bus.subscribe("risky", _mk(ok_seen))
    await bus.publish(Envelope("risky", {}, "t", "c1"))
    assert len(ok_seen) == 1  # sibling subscriber unaffected
    assert bus.metrics["delivery_errors"] == 1
    assert bus.errors and "boom" in bus.errors[0]["error"]


async def test_publish_without_subscribers_is_safe(bus):
    delivered = await bus.publish(Envelope("nobody-listens", {}, "t", "c1"))
    assert delivered == 0
    assert bus.metrics["messages_published"] == 1


def test_subscribe_rejects_non_coroutine(bus):
    with pytest.raises(TypeError):
        bus.subscribe("bad.topic", lambda env: None)


def test_topic_aliases_exported():
    # smoke: aliases exported for every topic used inter-agent
    from patchswarm import messages as M

    for name in (
        "INTENT", "RECON_REQUEST", "INVENTORY", "ANALYZE_REQUEST",
        "VERDICTS", "ENGINEER_REQUEST", "PATCH_RESULT", "REPORT_REQUEST",
        "REPORT_DONE", "AGENT_FAILED",
    ):
        assert isinstance(getattr(M, name), str)
    assert AGENT_FAILED == "agent.failed"
