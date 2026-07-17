from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

from .paths import GatePaths
from .state import load_state


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_checks(paths: GatePaths, which: Callable[[str], str | None] = shutil.which) -> list[Check]:
    state = load_state(paths.state)
    checks = [
        Check("uv", bool(which("uv")), which("uv") or "missing"),
        Check("node", bool(which("node")), which("node") or "missing"),
        Check("ngrok", bool(which("ngrok")), which("ngrok") or "missing"),
        Check("config", (paths.config / ".env").is_file(), str(paths.config / ".env")),
        Check("current release", paths.current.exists() and paths.current.resolve().is_dir(), state.active_release or "missing"),
    ]
    return checks
