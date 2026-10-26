"""CLI entry point: ``python -m patchswarm <path-to-manifest>``."""
from __future__ import annotations

import argparse
import json
import sys

from .mission import MissionRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="patchswarm",
        description="Run the five-agent vulnerability-response swarm on a dependency manifest.",
    )
    parser.add_argument("manifest", help="path to requirements.txt or package.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan patches without producing a patched artifact")
    parser.add_argument("--json", action="store_true", help="print the JSON report")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="mission timeout budget in seconds (default 15)")
    args = parser.parse_args(argv)

    runner = MissionRunner()
    report = runner.run_sync(
        {
            "manifest_path": args.manifest,
            "filename": args.manifest,
            "dry_run": args.dry_run,
        },
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        md = report.get("markdown", "")
        print(md or json.dumps(report, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
