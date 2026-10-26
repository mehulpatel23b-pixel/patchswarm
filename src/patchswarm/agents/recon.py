"""Recon agent - dependency manifest scanner."""
from __future__ import annotations

import asyncio

from ..manifest import Dependency, parse_manifest
from .base import AgentError, BaseAgent
from ..messages import INVENTORY, RECON_REQUEST


class ReconAgent(BaseAgent):
    """Stage 1: parse the dependency manifest into a structured inventory.

    Emits ``recon.inventory`` with the full inventory payload. Raises
    AgentError on unreadable/invalid manifests so the retry ladder gets a
    chance before failover happens.
    """

    name = "recon"
    subscriptions = (RECON_REQUEST,)

    async def handle(self, envelope) -> None:
        request = envelope.payload
        content = request.get("manifest_content")
        filename = request.get("filename") or "requirements.txt"
        if not content and request.get("manifest_path"):
            try:
                content = open(request["manifest_path"], encoding="utf-8").read()  # noqa: SIM115
            except OSError as exc:
                raise AgentError(f"cannot read manifest: {exc}") from exc
        if not content or not content.strip():
            raise AgentError("manifest content is empty or missing")

        deps = self.scan(content, filename)
        await asyncio.sleep(0)  # yield to the loop, simulating async IO
        await self.reply(
            envelope,
            INVENTORY,
            {
                "filename": filename,
                "packages": [d.to_dict() for d in deps],
                "scanned_count": len(deps),
                "unpinned_count": sum(1 for d in deps if d.version is None),
            },
        )

    @staticmethod
    def scan(content: str, filename: str) -> list[Dependency]:
        try:
            return parse_manifest(content, filename)
        except (ValueError, KeyError) as exc:
            raise AgentError(f"unparseable manifest: {exc}") from exc
