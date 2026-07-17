from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateState:
    schema_version: int = 1
    channel: str = "stable"
    active_version: str = ""
    active_release: str = ""
    previous_version: str = ""
    previous_release: str = ""
    commit: str | None = None


def load_state(path: Path) -> GateState:
    if not path.exists():
        return GateState()
    return GateState(**json.loads(path.read_text(encoding="utf-8")))


def save_state(path: Path, state: GateState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
