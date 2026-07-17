from pathlib import Path

from gate_cli.paths import GatePaths


def test_gate_paths_separate_releases_from_persistent_data(tmp_path):
    paths = GatePaths.from_home(tmp_path)

    assert paths.root == tmp_path / ".gate"
    assert paths.current == paths.root / "current"
    assert paths.releases == paths.root / "releases"
    assert paths.config == paths.root / "config"
    assert paths.data == paths.root / "data"
    assert paths.logs == paths.root / "logs"
    assert paths.skills == paths.root / "skills"
    assert paths.runtime == paths.root / "runtime"
    assert paths.state == paths.root / "state.json"


def test_gate_paths_create_persistent_directories(tmp_path):
    paths = GatePaths.from_home(tmp_path)

    paths.ensure_persistent()

    for directory in (paths.config, paths.data, paths.logs, paths.skills, paths.runtime, paths.releases, paths.cache, paths.backups):
        assert directory.is_dir()
