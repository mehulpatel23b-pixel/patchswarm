"""Agent base class - provides level-1 (agent-level) error recovery.

Every agent wraps its message handler in a bounded retry loop with
exponential backoff. If retries are exhausted, the agent publishes a
structured ``AGENT_FAILED`` message on the bus for orchestration-level
failover (level 2) instead of crashing the swarm.
"""
from __future__ import annotations

import asyncio

from ..bus import EventBus
from ..messages import AGENT_FAILED, Envelope


class AgentError(Exception):
    """Raised by agents for recoverable, domain-level failures."""


class BaseAgent:
    """Common scaffolding: bus wiring, retry, failure signalling."""

    name: str = "base"
    subscriptions: tuple = ()

    def __init__(
        self,
        bus: EventBus,
        max_retries: int = 2,
        backoff: float = 0.005,
    ) -> None:
        self.bus = bus
        self.max_retries = max_retries
        self.backoff = backoff
        self.handled = 0
        self.attempted = 0
        self.total_failures = 0
        self.failed_envelopes: list[Envelope] = []
        for topic in self.subscriptions:
            bus.subscribe(topic, self.receive)

    async def emit(self, topic: str, payload: dict, correlation_id: str) -> None:
        """Publish an envelope on the bus from this agent."""
        await self.bus.publish(
            Envelope(
                topic=topic,
                payload=payload,
                sender=self.name,
                correlation_id=correlation_id,
            )
        )

    async def reply(self, envelope: Envelope, topic: str, payload: dict) -> None:
        """Publish a follow-up on the same correlation id."""
        await self.bus.publish(
            Envelope(
                topic=topic,
                payload=payload,
                sender=self.name,
                correlation_id=envelope.correlation_id,
            )
        )

    async def receive(self, envelope: Envelope) -> bool:
        """Level-1 recovery: bounded retries with exponential backoff.

        Returns True when handled (possibly after retries), False when the
        agent declared failure. Declared failures are signalled on the
        ``AGENT_FAILED`` topic, never by raising out of the bus.
        """
        last_error: BaseException | None = None
        for attempt in range(self.max_retries + 1):  # +1 = first attempt
            self.attempted += 1
            try:
                await self.handle(envelope)
                self.handled += 1
                return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - deliberate catching
                last_error = exc
                self.total_failures += 1
                if attempt < self.max_retries:
                    await asyncio.sleep(self.backoff * (2 ** attempt))
        self.failed_envelopes.append(envelope)
        await self.bus.publish(
            Envelope(
                topic=AGENT_FAILED,
                payload={
                    "agent": self.name,
                    "error": repr(last_error),
                    "failed_topic": envelope.topic,
                    "failed_payload": envelope.payload,
                },
                sender=self.name,
                correlation_id=envelope.correlation_id,
            )
        )
        return False

    async def handle(self, envelope: Envelope) -> None:
        raise NotImplementedError
