from __future__ import annotations

import re
from pathlib import Path


def version_notes(path: Path, version: str) -> str:
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^##\s+{re.escape(version)}\s*$\n(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(content)
    return match.group(1).strip() if match else ""
