"""Message envelope + topic registry shared by every agent on the swarm bus."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field


class Topics:
    """Canonical topic names. All inter-agent traffic uses these."""

    # Mission entry point
    INTENT = "mission.intent"

    # Stage 1: recon
    RECON_REQUEST = "recon.request"
    INVENTORY = "recon.inventory"

    # Stage 2: analysis
    ANALYZE_REQUEST = "analyzer.request"
    VERDICTS = "analyzer.verdicts"

    # Stage 3: engineering
    ENGINEER_REQUEST = "engineer.request"
    PATCH_RESULT = "engineer.patch_result"

    # Stage 4: reporting
    REPORT_REQUEST = "reporter.request"
    REPORT_DONE = "reporter.report_done"

    # Error / recovery channels
    AGENT_FAILED = "agent.failed"
    MISSION_EVENT = "mission.event"


@dataclass
class Envelope:
    """Envelope for every message on the bus.

    Each envelope carries a ``correlation_id`` that ties every stage of a
    mission together, so multiple missions can run concurrently on one bus
    without cross-talk.
    """

    topic: str
    payload: dict
    sender: str
    correlation_id: str
    attempts: int = 0
    ts: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return asdict(self)

    def with_payload(self, topic: str, payload: dict) -> "Envelope":
        """Create a follow-up envelope on the same correlation id."""
        return Envelope(
            topic=topic,
            payload=payload,
            sender=self.sender,
            correlation_id=self.correlation_id,
        )


# Module-level aliases so agents can `from .messages import <TOPIC>`
INTENT = Topics.INTENT
RECON_REQUEST = Topics.RECON_REQUEST
INVENTORY = Topics.INVENTORY
ANALYZE_REQUEST = Topics.ANALYZE_REQUEST
VERDICTS = Topics.VERDICTS
ENGINEER_REQUEST = Topics.ENGINEER_REQUEST
PATCH_RESULT = Topics.PATCH_RESULT
REPORT_REQUEST = Topics.REPORT_REQUEST
REPORT_DONE = Topics.REPORT_DONE
AGENT_FAILED = Topics.AGENT_FAILED
MISSION_EVENT = Topics.MISSION_EVENT
