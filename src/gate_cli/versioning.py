from __future__ import annotations

import re

_STABLE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def is_stable_tag(tag: str) -> bool:
    return _STABLE.fullmatch(tag) is not None


def _key(tag: str) -> tuple[int, int, int]:
    match = _STABLE.fullmatch(tag)
    if match is None:
        raise ValueError(f"Not a stable SemVer tag: {tag}")
    return tuple(int(part) for part in match.groups())


def select_latest_stable_tag(tags: list[str]) -> str | None:
    stable = [tag for tag in tags if is_stable_tag(tag)]
    return max(stable, key=_key) if stable else None
