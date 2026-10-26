"""Manifest parsing - pure-stdlib readers for requirements.txt and package.json."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict

_REQ_PATTERN = re.compile(
    r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._\-]*)"
    r"\s*(?P<op>==|>=|<=|~=|!=|>|<)?\s*"
    r"(?P<version>[0-9][0-9A-Za-z.\-]*)?"
)
_CARET_PATTERN = re.compile(r"[\^~>=<]*\s*(?P<version>\d+(?:\.\d+){0,2})")


@dataclass
class Dependency:
    name: str
    version: str | None
    source: str
    section: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_version(version: str | None):
    """Convert '1.2.3' -> (1, 2, 3). Returns None if unparseable."""
    if not version:
        return None
    parts = []
    for chunk in version.strip().split("."):
        digits = re.match(r"\d+", chunk)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts) if parts else None


def is_affected(installed: str | None, affected_spec: str) -> bool:
    """Evaluate a simple '<X.Y.Z' affected-spec against an installed version.

    Unpinned dependencies (version None) are treated as affected - the worst
    case - because they will float to whatever the resolver picks.
    """
    if not affected_spec.startswith("<"):
        raise ValueError(f"unsupported affected spec: {affected_spec!r}")
    bound = parse_version(affected_spec[1:])
    if bound is None:
        raise ValueError(f"unparseable bound in spec: {affected_spec!r}")
    installed_tuple = parse_version(installed)
    if installed_tuple is None:
        return True
    # Right-pad to equal length so (1, 2) < (1, 2, 3)
    width = max(len(installed_tuple), len(bound))
    left = installed_tuple + (0,) * (width - len(installed_tuple))
    right = bound + (0,) * (width - len(bound))
    return left < right


def parse_requirements(content: str) -> list[Dependency]:
    deps: list[Dependency] = []
    for raw in content.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-r", "--")):
            continue
        if ";" in line:  # environment markers
            line = line.split(";", 1)[0].strip()
        match = _REQ_PATTERN.match(line)
        if not match or not match.group("name"):
            continue
        deps.append(
            Dependency(
                name=match.group("name").lower(),
                version=match.group("version") or None,
                source="requirements.txt",
            )
        )
    return deps


def parse_package_json(content: str) -> list[Dependency]:
    data = json.loads(content)
    deps: list[Dependency] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in (data.get(section) or {}).items():
            match = _CARET_PATTERN.match(str(spec))
            deps.append(
                Dependency(
                    name=name.lower(),
                    version=match.group("version") if match else None,
                    source="package.json",
                    section=section,
                )
            )
    return deps


def parse_manifest(content: str, filename: str = "requirements.txt") -> list[Dependency]:
    """Dispatch on filename. Only stdlib formats are supported."""
    if filename.endswith(".json"):
        return parse_package_json(content)
    return parse_requirements(content)


def to_requirements_text(deps: list[Dependency]) -> str:
    """Render dependencies back as a fully pinned requirements.txt."""
    lines = []
    for dep in deps:
        lines.append(f"{dep.name}=={dep.version}" if dep.version else dep.name)
    return "\n".join(lines) + ("\n" if lines else "")
