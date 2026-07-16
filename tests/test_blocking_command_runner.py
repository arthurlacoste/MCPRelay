import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from blocking_command_runner import BlockingCommandRunner


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
