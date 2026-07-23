from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import replace
from pathlib import Path

from .paths import GatePaths
from .state import GateState, load_state, save_state


def _switch_symlink(link: Path, target: Path) -> None:
    temporary = link.with_name(f".{link.name}.next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def activate_release(paths: GatePaths, release: Path, version: str, *, channel: str, commit: str | None = None) -> GateState:
    if not release.is_dir():
        raise FileNotFoundError(release)
    current = load_state(paths.state)
    _switch_symlink(paths.current, release)
    updated = GateState(
        channel=channel,
        active_version=version,
        active_release=str(release),
        previous_version=current.active_version,
        previous_release=current.active_release,
        commit=commit,
    )
    save_state(paths.state, updated)
    return updated


def rollback_release(paths: GatePaths) -> GateState:
    current = load_state(paths.state)
    if not current.previous_release:
        raise RuntimeError("No previous Gate release is available.")
    previous = Path(current.previous_release)
    if not previous.is_dir():
        raise FileNotFoundError(previous)
    _switch_symlink(paths.current, previous)
    rolled_back = replace(
        current,
        active_version=current.previous_version,
        active_release=current.previous_release,
        previous_version=current.active_version,
        previous_release=current.active_release,
        commit=None,
    )
    save_state(paths.state, rolled_back)
    return rolled_back


def install_archive_release(paths: GatePaths, archive: Path, tag: str, *, validate, migrate=lambda old, new: None, channel: str = "stable", commit: str | None = None) -> GateState:
    version = tag[1:] if tag.startswith("v") else tag
    release = paths.releases / f"v{version}"
    staging = Path(tempfile.mkdtemp(prefix=f"gate-{version}-", dir=paths.cache))
    try:
        with tarfile.open(archive, "r:gz") as handle:
            handle.extractall(staging, filter="data")
        roots = [entry for entry in staging.iterdir() if entry.is_dir()]
        if len(roots) != 1:
            raise RuntimeError("Gate archive must contain exactly one root directory.")
        candidate = roots[0]
        validate(candidate)
        previous = load_state(paths.state).active_version
        migrate(previous, version)
        temporary = release.with_name(release.name + ".next")
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.move(str(candidate), temporary)
        shutil.rmtree(release, ignore_errors=True)
        os.replace(temporary, release)
        return activate_release(paths, release, version, channel=channel, commit=commit)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def validate_release(release: Path, *, runner=subprocess.run, uv: str | None = None) -> None:
    required = ("VERSION", "requirements.txt", "run.sh", "src/gate_cli")
    missing = [name for name in required if not (release / name).exists()]
    if missing:
        raise RuntimeError(f"Invalid Gate release, missing: {', '.join(missing)}")
    uv_binary = uv or shutil.which("uv")
    if not uv_binary:
        raise RuntimeError("uv is required to prepare a Gate release.")
    runner([uv_binary, "venv", "--python", "3.12", str(release / ".venv")], check=True)
    runner([uv_binary, "pip", "install", "--python", str(release / ".venv" / "bin" / "python"), "-r", str(release / "requirements.txt")], check=True)
    runner(["bash", "-n", str(release / "run.sh")], check=True)
    runner([str(release / ".venv" / "bin" / "python"), "-m", "compileall", "-q", str(release / "src")], check=True)


def prune_releases(paths: GatePaths, keep: int = 2) -> None:
    state = load_state(paths.state)
    protected = {state.active_release, state.previous_release}
    releases = sorted((path for path in paths.releases.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
    retained = 0
    for release in releases:
        if str(release) in protected or retained < keep:
            retained += 1
            continue
        shutil.rmtree(release, ignore_errors=True)


def perform_update(
    paths: GatePaths,
    current_version: str,
    *,
    edge: bool = False,
    stable: bool = False,
    target_version: str | None = None,
):
    from .remote import GitHubRepository
    repository = GitHubRepository()
    paths.ensure_persistent()
    archive = paths.cache / "gate-update.tar.gz"
    release_assets = None
    explicit_version = target_version is not None
    if explicit_version:
        from .versioning import is_prerelease_tag
        release_assets = repository.release_by_tag(target_version)
        target_version = release_assets.tag[1:]
        archive_url = release_assets.archive_url
        channel = "prerelease" if is_prerelease_tag(release_assets.tag) else "explicit"
        commit = None
    elif edge:
        sha = repository.latest_edge_sha()
        target_version = repository.edge_version(current_version.split("-edge+", 1)[0], sha)
        archive_url = repository.archive_url(sha)
        channel = "edge"
        commit = sha
    else:
        release_assets = repository.latest_stable_release()
        target_version = release_assets.tag[1:]
        archive_url = release_assets.archive_url
        channel = "stable"
        commit = None
    state = load_state(paths.state)
    if not explicit_version and state.active_version == target_version and (channel != "stable" or state.channel == "stable"):
        return state, False
    repository.download(archive_url, archive)
    if channel != "edge":
        from .integrity import checksum_for_tag, verify_sha256
        expected = checksum_for_tag(repository.text(release_assets.checksums_url), f"v{target_version}")
        verify_sha256(archive, expected)
    from .migrations import run_migrations
    updated = install_archive_release(
        paths, archive, target_version, validate=validate_release, channel=channel, commit=commit,
        migrate=lambda old, new: run_migrations(paths, old, new, []),
    )
    prune_releases(paths)
    archive.unlink(missing_ok=True)
    return updated, True
