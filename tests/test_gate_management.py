import io
import os
import tarfile
from pathlib import Path

from gate_cli.doctor import run_checks
from gate_cli.logs import selected_logs
from gate_cli.paths import GatePaths
from gate_cli.state import GateState, save_state
from gate_cli.uninstall import uninstall
from gate_cli.updater import install_archive_release


def _archive(path: Path, version: str = "0.2.0") -> None:
    source = path.parent / "source"
    source.mkdir()
    (source / "VERSION").write_text(version + "\n")
    (source / "requirements.txt").write_text("")
    (source / "run.sh").write_text("#!/usr/bin/env bash\n")
    with tarfile.open(path, "w:gz") as handle:
        handle.add(source, arcname="MCPRelay-test")


def test_install_archive_release_extracts_and_activates(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    archive = tmp_path / "release.tar.gz"
    _archive(archive)

    state = install_archive_release(paths, archive, "v0.2.0", validate=lambda release: None)

    assert state.active_version == "0.2.0"
    assert paths.current.resolve() == (paths.releases / "v0.2.0").resolve()


def test_doctor_reports_missing_and_present_requirements(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    save_state(paths.state, GateState(active_version="0.1.0", active_release=str(paths.releases / "v0.1.0")))

    checks = run_checks(paths, which=lambda name: "/bin/true" if name in {"uv", "node", "ngrok"} else None)

    assert any(check.name == "uv" and check.ok for check in checks)
    assert any(check.name == "current release" and not check.ok for check in checks)


def test_selected_logs_filters_sources(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    gateway = paths.logs / "services" / "gateway.log"
    ngrok = paths.logs / "ngrok.log"
    gateway.parent.mkdir()
    gateway.write_text("gateway")
    ngrok.write_text("ngrok")

    assert selected_logs(paths, gateway=True, ngrok=False) == [gateway]
    assert selected_logs(paths, gateway=False, ngrok=True) == [ngrok]


def test_uninstall_preserves_user_data_without_purge(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    (paths.config / ".env").write_text("secret")
    (paths.data / "state.db").write_text("data")
    (paths.releases / "v0.1.0").mkdir()
    paths.current.symlink_to(paths.releases / "v0.1.0")
    launcher = tmp_path / ".local" / "bin" / "gate"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("launcher")

    uninstall(paths, launcher, purge=False)

    assert paths.config.exists()
    assert paths.data.exists()
    assert not paths.releases.exists()
    assert not launcher.exists()
