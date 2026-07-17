import json

from gate_cli.paths import GatePaths
from gate_cli.state import GateState, load_state, save_state


def test_state_round_trip_is_atomic_and_preserves_release_metadata(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    state = GateState(channel="stable", active_version="0.1.0", active_release=str(paths.releases / "v0.1.0"))

    save_state(paths.state, state)

    assert load_state(paths.state) == state
    assert json.loads(paths.state.read_text())["schema_version"] == 1
    assert not list(paths.root.glob("state.json.*.tmp"))
