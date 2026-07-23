from pathlib import Path

from gate_cli.paths import GatePaths
from gate_cli.state import GateState, load_state, save_state
from gate_cli.updater import activate_release, rollback_release


def test_activate_release_switches_symlink_and_tracks_previous_version(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    old = paths.releases / "v0.1.0"
    new = paths.releases / "v0.2.0"
    old.mkdir()
    new.mkdir()
    paths.current.symlink_to(old)
    save_state(paths.state, GateState(active_version="0.1.0", active_release=str(old)))

    activate_release(paths, new, "0.2.0", channel="stable")

    assert paths.current.resolve() == new.resolve()
    state = load_state(paths.state)
    assert state.active_version == "0.2.0"
    assert state.previous_version == "0.1.0"


def test_rollback_switches_to_previous_release(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    old = paths.releases / "v0.1.0"
    new = paths.releases / "v0.2.0"
    old.mkdir()
    new.mkdir()
    paths.current.symlink_to(new)
    save_state(paths.state, GateState(active_version="0.2.0", active_release=str(new), previous_version="0.1.0", previous_release=str(old)))

    rollback_release(paths)

    assert paths.current.resolve() == old.resolve()
    assert load_state(paths.state).active_version == "0.1.0"

def test_validate_release_rejects_incomplete_archive(tmp_path):
    from gate_cli.updater import validate_release
    release = tmp_path / "release"
    release.mkdir()
    (release / "VERSION").write_text("0.2.0")

    try:
        validate_release(release)
    except RuntimeError as error:
        assert "requirements.txt" in str(error)
    else:
        raise AssertionError("incomplete release accepted")

def test_validate_release_prepares_virtualenv_and_checks_shell(tmp_path):
    from gate_cli.updater import validate_release
    release = tmp_path / "release"
    (release / "src" / "gate_cli").mkdir(parents=True)
    (release / "VERSION").write_text("0.2.0")
    (release / "requirements.txt").write_text("")
    (release / "run.sh").write_text("#!/usr/bin/env bash\n")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        class Result: returncode = 0
        return Result()

    validate_release(release, runner=runner, uv="/usr/bin/uv")

    assert ["/usr/bin/uv", "venv", "--python", "3.12", str(release / ".venv")] in calls
    assert ["bash", "-n", str(release / "run.sh")] in calls

def test_install_archive_runs_migrations_before_activation(tmp_path):
    import tarfile
    from gate_cli.updater import install_archive_release

    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    old = paths.releases / "v0.1.0"
    old.mkdir()
    paths.current.symlink_to(old)
    save_state(paths.state, GateState(active_version="0.1.0", active_release=str(old)))

    source = tmp_path / "source"
    (source / "src" / "gate_cli").mkdir(parents=True)
    (source / "VERSION").write_text("0.2.0")
    (source / "requirements.txt").write_text("")
    (source / "run.sh").write_text("#!/usr/bin/env bash\n")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(source, arcname="Gate-test")
    events = []

    install_archive_release(
        paths,
        archive,
        "0.2.0",
        validate=lambda release: events.append("validate"),
        migrate=lambda old, new: events.append(f"migrate:{old}:{new}"),
    )

    assert events == ["validate", "migrate:0.1.0:0.2.0"]
    assert load_state(paths.state).active_version == "0.2.0"


def test_explicit_prerelease_uses_exact_release_and_checksum(monkeypatch, tmp_path):
    from gate_cli.paths import GatePaths
    from gate_cli.remote import ReleaseAssets
    from gate_cli.state import GateState, save_state
    import gate_cli.integrity as integrity
    import gate_cli.migrations as migrations
    import gate_cli.remote as remote
    import gate_cli.updater as updater

    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    save_state(paths.state, GateState(active_version="0.2.0", active_release="/old", channel="stable"))
    events = []

    class Repository:
        def release_by_tag(self, version):
            events.append(("release", version))
            return ReleaseAssets("v0.1.14-beta.1", "https://archive", "https://sums")
        def download(self, url, destination):
            destination.write_bytes(b"archive")
            events.append(("download", url))
        def text(self, url):
            events.append(("checksums", url))
            return "abc  gate-v0.1.14-beta.1.tar.gz\n"

    monkeypatch.setattr(remote, "GitHubRepository", Repository)
    monkeypatch.setattr(integrity, "checksum_for_tag", lambda text, tag: events.append(("checksum", tag)) or "abc")
    monkeypatch.setattr(integrity, "verify_sha256", lambda archive, expected: events.append(("verify", expected)))
    monkeypatch.setattr(migrations, "run_migrations", lambda *args: None)
    monkeypatch.setattr(updater, "install_archive_release", lambda paths, archive, tag, **kwargs: GateState(active_version=tag, active_release="/new", channel=kwargs["channel"]))
    monkeypatch.setattr(updater, "prune_releases", lambda paths: None)

    state, changed = updater.perform_update(paths, "0.2.0", target_version="0.1.14-beta.1")

    assert changed
    assert state.active_version == "0.1.14-beta.1"
    assert state.channel == "prerelease"
    assert ("release", "0.1.14-beta.1") in events
    assert ("checksum", "v0.1.14-beta.1") in events
    assert ("verify", "abc") in events


def test_explicit_stable_downgrade_uses_explicit_channel(monkeypatch, tmp_path):
    from gate_cli.paths import GatePaths
    from gate_cli.remote import ReleaseAssets
    from gate_cli.state import GateState, save_state
    import gate_cli.integrity as integrity
    import gate_cli.migrations as migrations
    import gate_cli.remote as remote
    import gate_cli.updater as updater

    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    save_state(paths.state, GateState(active_version="0.2.0", active_release="/old", channel="stable"))

    class Repository:
        def release_by_tag(self, version): return ReleaseAssets("v0.1.13", "https://archive", "https://sums")
        def download(self, url, destination): destination.write_bytes(b"archive")
        def text(self, url): return "abc  gate-v0.1.13.tar.gz\n"

    monkeypatch.setattr(remote, "GitHubRepository", Repository)
    monkeypatch.setattr(integrity, "checksum_for_tag", lambda text, tag: "abc")
    monkeypatch.setattr(integrity, "verify_sha256", lambda archive, expected: None)
    monkeypatch.setattr(migrations, "run_migrations", lambda *args: None)
    monkeypatch.setattr(updater, "install_archive_release", lambda paths, archive, tag, **kwargs: GateState(active_version=tag, active_release="/new", channel=kwargs["channel"]))
    monkeypatch.setattr(updater, "prune_releases", lambda paths: None)

    state, changed = updater.perform_update(paths, "0.2.0", target_version="v0.1.13")

    assert changed
    assert state.active_version == "0.1.13"
    assert state.channel == "explicit"


def test_explicit_same_version_forces_reinstall(monkeypatch, tmp_path):
    from gate_cli.paths import GatePaths
    from gate_cli.remote import ReleaseAssets
    from gate_cli.state import GateState, save_state
    import gate_cli.integrity as integrity
    import gate_cli.migrations as migrations
    import gate_cli.remote as remote
    import gate_cli.updater as updater

    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    save_state(paths.state, GateState(active_version="0.1.14", active_release="/old", channel="stable"))
    events = []

    class Repository:
        def release_by_tag(self, version):
            return ReleaseAssets("v0.1.14", "https://archive", "https://sums")
        def download(self, url, destination):
            events.append("download")
            destination.write_bytes(b"archive")
        def text(self, url): return "abc  gate-v0.1.14.tar.gz\n"

    monkeypatch.setattr(remote, "GitHubRepository", Repository)
    monkeypatch.setattr(integrity, "checksum_for_tag", lambda text, tag: "abc")
    monkeypatch.setattr(integrity, "verify_sha256", lambda archive, expected: None)
    monkeypatch.setattr(migrations, "run_migrations", lambda *args: None)
    monkeypatch.setattr(updater, "install_archive_release", lambda paths, archive, tag, **kwargs: GateState(active_version=tag, active_release="/new", channel=kwargs["channel"]))
    monkeypatch.setattr(updater, "prune_releases", lambda paths: None)

    state, changed = updater.perform_update(paths, "0.1.14", target_version="0.1.14")

    assert changed
    assert state.active_release == "/new"
    assert events == ["download"]
