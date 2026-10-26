#!/usr/bin/env python3
"""Patchswarm end-to-end demo.

Scans two manifests with the five-agent swarm (one clean-ish Python
requirements file, one JavaScript package.json), then shows the
mission-level failover path on a corrupted manifest. Writes the reports
to examples/output/ and prints the headline metrics.

Run from the repo root:

    PYTHONPATH=src python3 examples/demo.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from patchswarm import MissionRunner  # noqa: E402
from patchswarm.report import render_markdown  # noqa: E402

REQUIREMENTS = """\
# Mission A: a deliberately outdated Python service
requests==2.25.1
flask==2.0.1
django==4.1.0
jinja2==3.0.0
pyyaml>=4.0
sqlalchemy==2.0.20
"""

PACKAGE_JSON = """\
{
  "name": "web-dashboard",
  "dependencies": {
    "lodash": "^4.17.15",
    "minimist": "~1.2.0",
    "express": "^4.18.2"
  },
  "devDependencies": {
    "left-pad": "1.3.0"
  }
}
"""


async def main() -> None:
    runner = MissionRunner()
    missions = [
        ("py-service", {"manifest_content": REQUIREMENTS, "filename": "requirements.txt"}),
        ("js-dashboard", {"manifest_content": PACKAGE_JSON, "filename": "package.json"}),
        ("corrupted", {"manifest_content": "{ not json !!", "filename": "package.json"}),
    ]

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)

    for label, mission_input in missions:
        started = time.perf_counter()
        report = await runner.run(mission_input, timeout=10.0)
        elapsed = (time.perf_counter() - started) * 1000
        metrics = report["metrics"]
        print("=" * 68)
        print(f"mission  : {label} ({report['mission_id']})")
        print(f"status   : {report['status']}")
        print(f"scanned  : {metrics['packages_scanned']} packages "
              f"({metrics['unpinned_packages']} unpinned)")
        sev = metrics["by_severity"]
        print(f"findings : {metrics['vulnerabilities_found']} "
              f"(critical={sev.get('critical', 0)} high={sev.get('high', 0)} "
              f"medium={sev.get('medium', 0)} low={sev.get('low', 0)})")
        print(f"risk     : {metrics['aggregated_risk']}/100")
        print(f"patches  : {metrics['patches_proposed']} proposed, "
              f"validation {'PASSED' if metrics['validation_passed'] else 'FAILED'}")
        print(f"stages   : {' -> '.join(metrics['stages_completed']) or 'none (failover)'}")
        print(f"wall time: {elapsed:.1f} ms")
        for err in report["errors"]:
            print(f"  ! {err}")
        md = report.get("markdown") or render_markdown(report)
        path = os.path.join(out_dir, f"{label}-report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"report   : {path}")

    print("=" * 68)
    print("(+ json dump of mission 1)")
    import json
    first = runner.orchestrator.missions
    print(json.dumps({k: v["status"] for k, v in first.items()}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
