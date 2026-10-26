"""Bundled offline security-advisory database (illustrative sample data).

In production this module would be replaceable with an OSV / GitHub
Security Advisories feed; the swarm only depends on the record shape:

    {"id", "package", "severity", "affected", "fixed_in", "summary"}

Severity scale (highest first): critical, high, medium, low.
``affected`` uses the simple form ``"<X.Y.Z"`` - every version strictly
older than the bound is vulnerable.
"""
from __future__ import annotations

SEVERITIES = ("critical", "high", "medium", "low")
WEIGHTS = {"critical": 90, "high": 70, "medium": 45, "low": 15}

ADVISORIES = [
    {
        "id": "PSW-0001",
        "package": "requests",
        "severity": "critical",
        "affected": "<2.31.0",
        "fixed_in": "2.31.0",
        "summary": "Authorization headers leaked to same-host redirects (CVE-2023-32681 analogue).",
    },
    {
        "id": "PSW-0002",
        "package": "flask",
        "severity": "high",
        "affected": "<2.2.5",
        "fixed_in": "2.2.5",
        "summary": "Session cookie signature collision allows crafted session fixation.",
    },
    {
        "id": "PSW-0003",
        "package": "django",
        "severity": "high",
        "affected": "<4.2.8",
        "fixed_in": "4.2.8",
        "summary": "Potential email-header injection in the password-reset flow.",
    },
    {
        "id": "PSW-0004",
        "package": "jinja2",
        "severity": "high",
        "affected": "<3.1.3",
        "fixed_in": "3.1.3",
        "summary": "Sandbox breakout via str.format attribute traversal.",
    },
    {
        "id": "PSW-0005",
        "package": "pyyaml",
        "severity": "high",
        "affected": "<5.4",
        "fixed_in": "5.4",
        "summary": "Arbitrary code execution when loading untrusted YAML with full_load().",
    },
    {
        "id": "PSW-0006",
        "package": "pillow",
        "severity": "critical",
        "affected": "<10.0.0",
        "fixed_in": "10.0.0",
        "summary": "Heap buffer over-read decoding malicious WebP images.",
    },
    {
        "id": "PSW-0007",
        "package": "urllib3",
        "severity": "medium",
        "affected": "<1.26.5",
        "fixed_in": "1.26.5",
        "summary": "Cookie persistence allows leak of session tokens across origins.",
    },
    {
        "id": "PSW-0008",
        "package": "numpy",
        "severity": "medium",
        "affected": "<1.24.0",
        "fixed_in": "1.24.0",
        "summary": "Out-of-bounds read in pickle loading of crafted arrays.",
    },
    {
        "id": "PSW-0009",
        "package": "lodash",
        "severity": "high",
        "affected": "<4.17.21",
        "fixed_in": "4.17.21",
        "summary": "Prototype pollution via zipObjectDeep merge paths.",
    },
    {
        "id": "PSW-0010",
        "package": "minimist",
        "severity": "medium",
        "affected": "<1.2.6",
        "fixed_in": "1.2.6",
        "summary": "Prototype pollution via CLI argument key paths.",
    },
]


def advisories_for(package: str) -> list[dict]:
    """All advisories whose package matches (case-insensitive)."""
    needle = package.strip().lower()
    return [a for a in ADVISORIES if a["package"].lower() == needle]


def max_severity(severities) -> str:
    """Return the most severe of the given severities."""
    return max(severities, key=lambda s: WEIGHTS.get(s, 0), default="none")
