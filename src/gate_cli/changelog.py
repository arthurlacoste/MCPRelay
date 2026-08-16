from __future__ import annotations

from pathlib import Path

from changelog_parser import changelog_section


def version_notes(path: Path, version: str) -> str:
    if not path.exists():
        return ""
    section = changelog_section(path.read_text(encoding="utf-8"), version)
    return section or ""
