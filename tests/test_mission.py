"""End-to-end swarm missions: happy paths, artifacts, concurrency."""
import asyncio

from patchswarm import MissionRunner
from patchswarm.report import render_markdown

REQUIREMENTS = """\
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
  "dependencies": {"lodash": "^4.17.15", "minimist": "~1.2.0"},
  "devDependencies": {"jest": "29.0.0"}
}
"""


async def test_mission_happy_path_produces_full_report():
    runner = MissionRunner()
    report = await runner.run(
        {"manifest_content": REQUIREMENTS, "filename": "requirements.txt"},
        timeout=10.0,
        mission_id="mission-alpha",
    )
    assert report["status"] == "ok"
    assert report["mission_id"] == "mission-alpha"
    metrics = report["metrics"]
    assert metrics["packages_scanned"] == 6
    assert metrics["vulnerabilities_found"] == 5  # requests, flask, django, jinja2, pyyaml
    assert metrics["by_severity"]["critical"] == 1
    assert metrics["by_severity"]["high"] == 4
    assert metrics["validation_passed"] is True
    assert metrics["stages_completed"] == ["inventory", "analysis", "patch"]
    assert metrics["agent_errors"] == 0
    patched = report["patched_manifest"]
    for name, safe in {
        "requests": "2.31.0",
        "flask": "2.2.5",
        "django": "4.2.8",
        "jinja2": "3.1.3",
        "pyyaml": "5.4",
        "sqlalchemy": "2.0.20",
    }.items():
        assert f"{name}=={safe}" in patched, patched
    # correlation id threading: every bus message belonged to the mission
    assert all(
        env.correlation_id == "mission-alpha" for env in runner.bus.log
    )


async def test_package_json_mission_scans_dev_dependencies():
    runner = MissionRunner()
    report = await runner.run({"manifest_content": PACKAGE_JSON, "filename": "package.json"})
    names = {finding["package"] for finding in report["findings"]}
    assert names == {"lodash", "minimist"}
    assert report["status"] == "ok"
    assert report["metrics"]["packages_scanned"] == 3


async def test_clean_manifest_reports_zero_findings():
    runner = MissionRunner()
    report = await runner.run({"manifest_content": "rich==13.7.0\n"} )
    assert report["status"] == "ok"
    assert report["metrics"]["vulnerabilities_found"] == 0
    assert report["metrics"]["aggregated_risk"] == 0
    assert report["metrics"]["validation_passed"] is True
    assert report["patch_plan"] == []


async def test_dry_run_mission_plans_but_does_not_patch():
    runner = MissionRunner()
    report = await runner.run(
        {"manifest_content": REQUIREMENTS, "filename": "requirements.txt", "dry_run": True}
    )
    assert report["status"] == "ok"
    assert report["metrics"]["patches_proposed"] == 5
    assert report["patched_manifest"] == ""
    assert report["metrics"]["validation_passed"] is False
    assert any(c["name"] == "dry_run" for c in report["validation_checks"])


async def test_markdown_rendering_is_report_shaped():
    runner = MissionRunner()
    report = await runner.run({"manifest_content": REQUIREMENTS})
    md = report["markdown"]
    assert "# Patchswarm Security Mission Report" in md
    assert "## Findings" in md
    assert "## Patch plan" in md
    assert "## Validation gate" in md
    assert "requests" in md and "2.31.0" in md
    # every report must render standalone too
    assert render_markdown(report).startswith("# Patchswarm")


async def test_concurrent_missions_stay_isolated():
    """Two missions on one bus: artifacts never cross correlation ids."""
    runner = MissionRunner()
    a, b = await asyncio.gather(
        runner.run({"manifest_content": REQUIREMENTS}, mission_id="mission-a"),
        runner.run({"manifest_content": PACKAGE_JSON, "filename": "package.json"}, mission_id="mission-b"),
    )
    # gather preserves order: a is mission-a, b is mission-b
    assert a["mission_id"] == "mission-a"
    assert b["mission_id"] == "mission-b"
    assert a["metrics"]["packages_scanned"] == 6
    assert b["metrics"]["packages_scanned"] == 3
    assert a["manifest"] == "requirements.txt"
    assert b["manifest"] == "package.json"


async def test_runner_reusable_across_missions():
    runner = MissionRunner()
    first = await runner.run({"manifest_content": REQUIREMENTS}, mission_id="m1")
    second = await runner.run({"manifest_content": "rich==13.7.0\n"}, mission_id="m2")
    assert first["mission_id"] == "m1" and first["metrics"]["vulnerabilities_found"] == 5
    assert second["mission_id"] == "m2" and second["metrics"]["vulnerabilities_found"] == 0


def test_run_sync_wrapper():
    runner = MissionRunner()
    report = runner.run_sync({"manifest_content": "requests==2.25.1\n"})
    assert report["status"] == "ok"
    assert report["metrics"]["vulnerabilities_found"] == 1
