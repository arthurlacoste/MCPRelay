from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .versioning import select_latest_stable_tag


@dataclass(frozen=True)
class StableRelease:
    tag: str
    archive_url: str
    checksums_url: str


class GitHubRepository:
    def __init__(self, repo: str = "arthurlacoste/gate", opener: Callable = urllib.request.urlopen):
        self.repo = repo
        self.opener = opener
        self.api = f"https://api.github.com/repos/{repo}"

    def _json(self, url: str):
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Gate-Updater"})
        with self.opener(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def latest_stable_tag(self) -> str:
        items = self._json(f"{self.api}/tags?per_page=100")
        tag = select_latest_stable_tag([item.get("name", "") for item in items])
        if not tag:
            raise RuntimeError("No stable Gate tag found.")
        return tag

    def latest_stable_release(self) -> StableRelease:
        release = self._json(f"{self.api}/releases/latest")
        tag = str(release.get("tag_name", ""))
        archive_name = f"gate-{tag}.tar.gz"
        assets = {asset.get("name"): asset.get("browser_download_url") for asset in release.get("assets", [])}
        archive_url = assets.get(archive_name)
        checksums_url = assets.get("SHA256SUMS")
        if not tag or not archive_url or not checksums_url:
            raise RuntimeError(f"GitHub Release {tag or '<unknown>'} is missing required assets: {archive_name}, SHA256SUMS.")
        return StableRelease(tag=tag, archive_url=str(archive_url), checksums_url=str(checksums_url))

    def latest_edge_sha(self) -> str:
        return str(self._json(f"{self.api}/commits/main")["sha"])

    @staticmethod
    def edge_version(base_version: str, sha: str) -> str:
        return f"{base_version}-edge+{sha[:7]}"

    def archive_url(self, ref: str) -> str:
        return f"https://github.com/{self.repo}/archive/{ref}.tar.gz"

    def text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "Gate-Updater"})
        with self.opener(request) as response:
            return response.read().decode("utf-8")

    def download(self, url: str, destination: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Gate-Updater"})
        with self.opener(request) as response, destination.open("wb") as handle:
            handle.write(response.read())
