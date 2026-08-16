from __future__ import annotations

import re


def changelog_section(content: str, version: str) -> str | None:
    """Return one release section from plain or Release Please Markdown headings."""
    normalized = version.removeprefix("v")
    heading = re.compile(
        rf"^##\s+(?:\[)?v?{re.escape(normalized)}"
        rf"(?:\](?:\([^\n]*\))?)?(?:\s+\([^\n)]*\))?\s*$",
        re.MULTILINE,
    )
    match = heading.search(content)
    if match is None:
        return None
    next_heading = re.search(r"^##\s+", content[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(content)
    return content[match.end():end].strip()
