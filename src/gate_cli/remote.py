from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .versioning import normalize_tag, select_latest_stable_tag


@dataclass(frozen=True)
class ReleaseAssets:
    tag: str
    archive_url: str
    checksums_url: str


class GitHubRepository:
    def __init__(self, repo: str = "spelcc/gate", opener: Callable = urllib.request.urlopen):
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

    def latest_stable_release(self) -> ReleaseAssets:
        release = self._json(f"{self.api}/releases/latest")
        tag = str(release.get("tag_name", ""))
        archive_name = f"gate-{tag}.tar.gz"
        assets = {asset.get("name"): asset.get("browser_download_url") for asset in release.get("assets", [])}
        archive_url = assets.get(archive_name)
        checksums_url = assets.get("SHA256SUMS")
        if not tag or not archive_url or not checksums_url:
            raise RuntimeError(f"GitHub Release {tag or '<unknown>'} is missing required assets: {archive_name}, SHA256SUMS.")
        return ReleaseAssets(tag=tag, archive_url=str(archive_url), checksums_url=str(checksums_url))

    def release_by_tag(self, version: str) -> ReleaseAssets:
        tag = normalize_tag(version)
        encoded = urllib.parse.quote(tag, safe="")
        try:
            release = self._json(f"{self.api}/releases/tags/{encoded}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RuntimeError(f"Gate release {tag} was not found.") from exc
            raise
        actual_tag = str(release.get("tag_name", ""))
        if actual_tag != tag:
            raise RuntimeError(f"GitHub returned release {actual_tag or '<unknown>'} instead of {tag}.")
        archive_name = f"gate-{tag}.tar.gz"
        assets = {asset.get("name"): asset.get("browser_download_url") for asset in release.get("assets", [])}
        archive_url = assets.get(archive_name)
        checksums_url = assets.get("SHA256SUMS")
        if not archive_url or not checksums_url:
            raise RuntimeError(f"GitHub Release {tag} is missing required assets: {archive_name}, SHA256SUMS.")
        return ReleaseAssets(tag=tag, archive_url=str(archive_url), checksums_url=str(checksums_url))

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
