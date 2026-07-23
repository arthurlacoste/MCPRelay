from __future__ import annotations

import re

_SEMVER = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def normalize_tag(value: str) -> str:
    candidate = value.strip()
    match = _SEMVER.fullmatch(candidate)
    if match is None or match.group(5) is not None:
        raise ValueError(f"Invalid Gate version: {value!r}")
    return candidate if candidate.startswith("v") else f"v{candidate}"


def is_semver_tag(tag: str) -> bool:
    match = _SEMVER.fullmatch(tag)
    return tag.startswith("v") and match is not None and match.group(5) is None


def is_stable_tag(tag: str) -> bool:
    match = _SEMVER.fullmatch(tag)
    return tag.startswith("v") and match is not None and match.group(4) is None and match.group(5) is None


def is_prerelease_tag(tag: str) -> bool:
    match = _SEMVER.fullmatch(tag)
    return tag.startswith("v") and match is not None and match.group(4) is not None and match.group(5) is None


def _key(tag: str) -> tuple[int, int, int]:
    if not is_stable_tag(tag):
        raise ValueError(f"Not a stable SemVer tag: {tag}")
    match = _SEMVER.fullmatch(tag)
    assert match is not None
    return tuple(int(part) for part in match.groups()[:3])


def select_latest_stable_tag(tags: list[str]) -> str | None:
    stable = [tag for tag in tags if is_stable_tag(tag)]
    return max(stable, key=_key) if stable else None
