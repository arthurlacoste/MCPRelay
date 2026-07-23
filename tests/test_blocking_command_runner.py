import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blocking_command_runner import BlockingCommandRunner
from realtime_calls import RealtimeCallStore


def test_blocking_runner_waits_and_renders_historical_output(tmp_path):
    runner = BlockingCommandRunner(tmp_path / "logs")
    result = runner.run(
        f'"{sys.executable}" -c "import sys; print(\'hello\'); print(\'bad\', file=sys.stderr)"',
        cwd=tmp_path,
        timeout_seconds=5,
    )

    rendered = result.render()
    assert result.exit_code == 0
    assert "EXIT CODE: 0" in rendered
    assert "STDOUT:\nhello" in rendered
    assert "STDERR:\nbad" in rendered
    assert result.log_path.is_file()
    assert "[stderr] bad" in result.log_path.read_text()


def test_blocking_runner_reports_timeout(tmp_path):
    runner = BlockingCommandRunner(tmp_path / "logs")
    result = runner.run(
        f'"{sys.executable}" -c "import time; time.sleep(5)"',
        timeout_seconds=0.1,
    )

    assert result.timed_out is True
    assert "TIMED OUT AFTER: 0.1s" in result.render()


def test_blocking_runner_publishes_monitor_states(tmp_path):
    store = RealtimeCallStore()
    runner = BlockingCommandRunner(
        tmp_path / "logs",
        state_observer=store.update,
    )

    runner.run(
        f'"{sys.executable}" -c "print(\'observed\')"',
        purpose="Verify blocking monitor",
    )

    calls = store.snapshot()["calls"]
    assert len(calls) == 1
    assert calls[0]["status"] == "success"
    assert calls[0]["purpose"] == "Verify blocking monitor"
    assert calls[0]["exit_code"] == 0
