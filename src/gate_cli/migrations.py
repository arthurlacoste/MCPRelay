from __future__ import annotations

import shutil
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .paths import GatePaths


@dataclass(frozen=True)
class MigrationContext:
    paths: GatePaths
    old_version: str
    new_version: str


class MigrationError(RuntimeError):
    def __init__(self, message: str, report: Path, issue_url: str):
        super().__init__(message)
        self.report = report
        self.issue_url = issue_url


def _issue_url(old_version: str, new_version: str, report: Path, error: str) -> str:
    body = (
        f"Gate update migration failed.\n\n"
        f"From: {old_version}\nTo: {new_version}\n"
        f"Error: {error}\nLocal report: {report}\n"
    )
    query = urlencode({"title": f"Migration failure {old_version} to {new_version}", "body": body})
    return f"https://github.com/arthurlacoste/gate/issues/new?{query}"


def run_migrations(paths: GatePaths, old_version: str, new_version: str, migrations) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = paths.backups / f"migration-{stamp}"
    report = paths.logs / f"update-error-{stamp}.log"
    backup.mkdir(parents=True, exist_ok=False)
    if paths.config.exists():
        shutil.copytree(paths.config, backup / "config")
    context = MigrationContext(paths=paths, old_version=old_version, new_version=new_version)
    try:
        for migration in migrations:
            migration(context)
    except Exception as exc:
        shutil.rmtree(paths.config, ignore_errors=True)
        if (backup / "config").exists():
            shutil.copytree(backup / "config", paths.config)
        report.parent.mkdir(parents=True, exist_ok=True)
        safe_traceback = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        report.write_text(
            f"Gate migration failure\nFrom: {old_version}\nTo: {new_version}\n\n{safe_traceback}",
            encoding="utf-8",
        )
        issue_url = _issue_url(old_version, new_version, report, str(exc))
        raise MigrationError(str(exc), report, issue_url) from exc
