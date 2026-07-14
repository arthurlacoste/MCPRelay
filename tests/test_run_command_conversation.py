import json
import os
import shlex
import time
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_run_command_writes_conversation_event(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    result = mod.run_command(
        command=f'"{sys.executable}" -c "import sys; print(\'hello\'); print(\'error\', file=sys.stderr)"',
        conversation_id='conv-test',
        purpose='test command'
    )

    payload = json.loads((tmp_path / 'conv-test.jsonl').read_text().splitlines()[-1])
    stream_log = next(tmp_path.glob('command_*.log')).read_text()

    assert payload['tool'] == 'run_command'
    assert payload['arguments']['purpose'] == 'test command'
    assert payload['exit_code'] == 0
    assert 'logs/commands/' in payload['result_ref']
    assert 'created_files' not in payload
    assert 'EXIT CODE: 0' in result
    assert 'hello' in result
    assert 'error' in result
    assert 'EXIT CODE: 0' in stream_log
    assert 'hello' in stream_log
    assert '[stderr] error' in stream_log
    assert 'CREATED FILES' not in result
    assert 'CREATED FILES' not in stream_log


def test_run_command_does_not_scan_created_files(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    created_file = tmp_path / 'created.txt'

    result = mod.run_command(
        command=f'"{sys.executable}" -c "import os; from pathlib import Path; os.chdir(r\'{tmp_path}\'); Path(\'created.txt\').write_text(\'created\')"'
    )

    assert created_file.read_text() == 'created'
    assert str(created_file) not in result
    assert 'CREATED FILES' not in result


def test_run_command_no_output_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    mod.run_command(
        command=f'"{sys.executable}" -c "print(\'hidden\')"',
        conversation_id='conv-hidden'
    )

    payload = json.loads((tmp_path / 'conv-hidden.jsonl').read_text().splitlines()[-1])
    assert payload['result_included'] is False


def test_run_command_action_log_has_no_created_files(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    actions = []
    monkeypatch.setattr(mod, 'log_action', lambda action, payload=None: actions.append((action, payload)))

    mod.run_command(command=f'"{sys.executable}" -c "print(\'output\')"')

    end_payload = next(payload for action, payload in actions if action == 'run_command_end')
    assert end_payload['exit_code'] == 0
    assert 'created_files' not in end_payload


def test_run_command_timeout_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'

    result = mod.run_command(command=command, timeout_seconds=0.2)
    stream_log = next(tmp_path.glob('command_*.log')).read_text()

    assert 'TIMED OUT AFTER: 0.2s' in result
    assert 'TIMED OUT AFTER: 0.2s' in stream_log


def test_run_command_timeout_is_logged_in_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    mod.run_command(
        command=f'"{sys.executable}" -c "import time; time.sleep(5)"',
        conversation_id='timeout-test',
        timeout_seconds=0.2,
    )

    payload = json.loads((tmp_path / 'timeout-test.jsonl').read_text().splitlines()[-1])
    assert payload['timed_out'] is True
    assert payload['arguments']['timeout_seconds'] == 0.2


def test_timeout_kills_child_process(tmp_path, monkeypatch):
    if os.name == 'nt':
        pytest.skip('POSIX process-group assertion')

    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    pid_file = tmp_path / 'child.pid'
    child_code = (
        "import os,time,pathlib; "
        f"pathlib.Path(r'{pid_file}').write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "time.sleep(30)"
    )

    mod.run_command(
        command=f'"{sys.executable}" -c {shlex.quote(parent_code)}',
        timeout_seconds=0.4,
    )

    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f'child process {child_pid} survived timeout')
