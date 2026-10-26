"""Async pub/sub event bus - the backbone of swarm coordination."""
from __future__ import annotations

import asyncio
from collections import defaultdict

from .messages import Envelope


class EventBus:
    """A lightweight in-process publish/subscribe bus.

    - ``subscribe(topic, handler)`` registers an async handler.
    - ``publish(envelope)`` fans the envelope out to every handler that is
      subscribed to its topic, concurrently, preserving ordering guarantees
      of the single asyncio event loop.
    - The bus never crashes the publisher: handler exceptions are captured
      into ``self.errors`` and counted, so orchestration-level failover can
      inspect them. Agents are expected to implement their own retry policy
      (see ``agents.base.BaseAgent``).

    The bus also keeps lightweight metrics so the Reporter agent can quote
    real traffic numbers in mission reports.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, list] = defaultdict(list)
        self.metrics = {
            "messages_published": 0,
            "deliveries": 0,
            "delivery_errors": 0,
            "topics": 0,
        }
        self.errors: list[dict] = []
        self.log: list[Envelope] = []

    def subscribe(self, topic: str, handler) -> None:
        """Register an async handler ``handler(envelope)`` for a topic."""
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"handler for {topic!r} must be a coroutine function")
        if handler not in self._subscriptions[topic]:
            self._subscriptions[topic].append(handler)
        self.metrics["topics"] = len(self._subscriptions)

    def unsubscribe(self, topic: str, handler) -> bool:
        """Remove a handler. Returns True if it was registered."""
        handlers = self._subscriptions.get(topic)
        if not handlers or handler not in handlers:
            return False
        handlers.remove(handler)
        return True

    def subscribers(self, topic: str) -> list:
        return list(self._subscriptions.get(topic, ()))

    async def publish(self, envelope: Envelope) -> int:
        """Fan an envelope out to all subscribers of its topic.

        Returns the number of successful deliveries.
        """
        self.metrics["messages_published"] += 1
        self.log.append(envelope)
        handlers = self.subscribers(envelope.topic)
        if not handlers:
            return 0
        results = await asyncio.gather(
            *(h(envelope) for h in handlers), return_exceptions=True
        )
        delivered = 0
        for handler, result in zip(handlers, results):
            if isinstance(result, Exception):
                self.metrics["delivery_errors"] += 1
                self.errors.append(
                    {
                        "topic": envelope.topic,
                        "correlation_id": envelope.correlation_id,
                        "error": repr(result),
                    }
                )
            else:
                delivered += 1
        self.metrics["deliveries"] += delivered
        return delivered
