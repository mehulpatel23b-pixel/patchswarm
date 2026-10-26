"""Manifest parsing + advisory math: the swarm's domain primitives."""
import pytest

from patchswarm.manifest import (
    Dependency,
    is_affected,
    parse_manifest,
    parse_requirements,
    parse_version,
    to_requirements_text,
)
from patchswarm.agents.analyzer import AnalyzerAgent, count_by_severity, risk_score
from patchswarm.agents.engineer import EngineerAgent


def test_parse_requirements_basic_and_comments():
    content = "# header\nrequests==2.25.1\nflask>=2.0.1\n\nrich  # inline comment\nsqlalchemy==2.0.20\n"
    deps = parse_requirements(content)
    assert [d.name for d in deps] == ["requests", "flask", "rich", "sqlalchemy"]
    assert deps[0].version == "2.25.1"
    assert deps[2].version is None


def test_parse_requirements_skips_options_and_markers():
    content = "--index-url https://example.com/simple\nrequests==2.25.1; python_version > '3.8'\n"
    deps = parse_requirements(content)
    assert len(deps) == 1 and deps[0].name == "requests"
    assert deps[0].version == "2.25.1"


def test_parse_package_json_sections():
    content = (
        '{"dependencies": {"lodash": "^4.17.15", "minimist": "~1.2.0"}, '
        '"devDependencies": {"jest": "29.0.0"}}'
    )
    deps = parse_manifest(content, "package.json")
    assert {d.name for d in deps} == {"lodash", "minimist", "jest"}
    assert deps[0].version == "4.17.15"
    assert deps[-1].source == "package.json"
    assert deps[-1].section == "devDependencies"


def test_parse_version_padding_and_compare():
    assert parse_version("1.2") < parse_version("1.2.3")
    assert parse_version("2.31.0") > parse_version("2.9.9")  # not lexicographic
    assert parse_version(None) is None
    assert parse_version("") is None


def test_is_affected_semantics():
    assert is_affected("2.25.1", "<2.31.0") is True
    assert is_affected("2.31.0", "<2.31.0") is False  # fixed boundary
    assert is_affected(None, "<4.17.21") is True      # unpinned = worst case
    with pytest.raises(ValueError):
        is_affected("1.0", ">=2.0")


def test_analyzer_triage_orders_by_risk():
    packages = [
        {"name": "requests", "version": "2.25.1"},
        {"name": "numpy", "version": "1.23.0"},
        {"name": "rich", "version": "13.7.0"},
    ]
    verdicts = AnalyzerAgent.triage(packages)
    assert {v["package"] for v in verdicts} == {"requests", "numpy"}
    assert verdicts[0]["severity"] == "critical"  # highest risk first
    assert verdicts[0]["package"] == "requests"


def test_analyzer_counts_and_risk_score():
    verdicts = [
        {"severity": "critical", "risk": 90},
        {"severity": "high", "risk": 70},
        {"severity": "high", "risk": 70},
    ]
    assert count_by_severity(verdicts)["high"] == 2
    score = risk_score(verdicts)
    assert 0 < score <= 100
    assert risk_score([]) == 0
    # critical present -> bonus bump above the plain mean
    assert risk_score(verdicts) > int((90 + 70 + 70) / 3)


def test_engineer_plan_dedupes_multiple_advisories():
    verdicts = [
        {"package": "x", "installed": "1.0", "fixed_in": "3.0",
         "advisory_id": "A-1", "severity": "medium", "risk": 45},
        {"package": "x", "installed": "1.0", "fixed_in": "3.0",
         "advisory_id": "A-2", "severity": "critical", "risk": 90},
    ]
    plan = EngineerAgent.plan_patches(verdicts)
    assert len(plan) == 1
    assert plan[0]["severity"] == "critical"  # most severe governs
    assert plan[0]["advisory_ids"] == ["A-1", "A-2"]


def test_engineer_apply_and_validate_roundtrip():
    packages = [
        {"name": "requests", "version": "2.25.1"},
        {"name": "rich", "version": "13.7.0"},
    ]
    plan = [
        {"package": "requests", "target": "2.31.0", "action": "upgrade"},
        {"package": "rich", "target": "13.7.0", "action": "upgrade"},
    ]
    patched = EngineerAgent.apply_patches("requirements.txt", packages, plan)
    reparsed = parse_manifest(patched, "requirements.txt")
    assert {d.name: d.version for d in reparsed}["requests"] == "2.31.0"
    checks = EngineerAgent.validate(packages, plan, patched, dry_run=False)
    assert {c["name"]: c["passed"] for c in checks} == {
        "upgrades_sufficient": True,
        "artifact_integrity": True,
        "explicit_pinning": True,
    }


def test_engineer_dry_run_skips_artifact_and_fails_gate():
    packages = [{"name": "requests", "version": "2.25.1"}]
    plan = [{"package": "requests", "target": "2.31.0", "action": "upgrade"}]
    checks = EngineerAgent.validate(packages, plan, "", dry_run=True)
    gate = {c["name"]: c["passed"] for c in checks}
    assert "artifact_integrity" not in gate
    assert gate["upgrades_sufficient"] is False


def test_to_requirements_text_pins_everything():
    text = to_requirements_text(
        [
            Dependency("a", "1.0", "requirements.txt"),
            Dependency("b", "1.1", "requirements.txt"),
        ]
    )
    assert text == "a==1.0\nb==1.1\n"
