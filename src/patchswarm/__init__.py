"""patchswarm - an autonomous five-agent dependency-vulnerability response crew.

The swarm ingests a dependency manifest (requirements.txt or package.json),
collaborates over an async event bus to discover, triage, and patch known
vulnerabilities, and always produces a structured report.

Zero runtime dependencies - pure Python 3.9+ standard library.
"""

__version__ = "1.0.0"

from .bus import EventBus
from .messages import Envelope, Topics
from .mission import MissionRunner

__all__ = ["EventBus", "Envelope", "Topics", "MissionRunner", "__version__"]
