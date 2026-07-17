from __future__ import annotations

import shutil
from pathlib import Path

from .paths import GatePaths


def uninstall(paths: GatePaths, launcher: Path, *, purge: bool) -> None:
    launcher.unlink(missing_ok=True)
    if purge:
        shutil.rmtree(paths.root, ignore_errors=True)
        return
    paths.current.unlink(missing_ok=True)
    for directory in (paths.releases, paths.runtime, paths.cache, paths.backups):
        shutil.rmtree(directory, ignore_errors=True)
    paths.state.unlink(missing_ok=True)
