from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatePaths:
    root: Path
    current: Path
    releases: Path
    config: Path
    data: Path
    logs: Path
    skills: Path
    runtime: Path
    cache: Path
    backups: Path
    state: Path

    @classmethod
    def from_home(cls, home: Path) -> "GatePaths":
        root = home / ".gate"
        return cls(
            root=root,
            current=root / "current",
            releases=root / "releases",
            config=root / "config",
            data=root / "data",
            logs=root / "logs",
            skills=root / "skills",
            runtime=root / "runtime",
            cache=root / "cache",
            backups=root / "backups",
            state=root / "state.json",
        )

    def ensure_persistent(self) -> None:
        for directory in (
            self.root,
            self.releases,
            self.config,
            self.data,
            self.logs,
            self.skills,
            self.runtime,
            self.cache,
            self.backups,
        ):
            directory.mkdir(parents=True, exist_ok=True)
