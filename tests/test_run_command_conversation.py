import json
import os
import shlex
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from command_queue import CommandQueue
import mcp_gateway as mod


def install_queue(tmp_path, monkeypatch):
    old = mod.command_queue
    queue = CommandQueue(tmp_path / 'commands.sqlite3', tmp_path, worker_limit=4, on_event=mod.command_finished)
    monkeypatch.setattr(mod, 'command_queue', queue)
    old.close()
    return queue


def wait_final(queue, execution_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = queue.get_state(execution_id)
        if state['status'] in {'success', 'failed', 'timeout', 'cancelled'}:
            return state
        time.sleep(.02)
    pytest.fail('command did not finish')


def test_run_command_writes_conversation_event(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    queue = install_queue(tmp_path, monkeypatch)
    result = mod.run_command(
        command=f'"{sys.executable}" -c "import sys; print(\'hello\'); print(\'error\', file=sys.stderr)"',
        conversation_id='conv-test', purpose='test command',
    )
    assert result['status'] in {'queued', 'starting', 'running'}
    final = wait_final(queue, result['execution_id'])
    payload = json.loads((tmp_path / 'conv-test.jsonl').read_text().splitlines()[-1])
    stream_log = (tmp_path / f"{result['execution_id']}.log").read_text()
    assert payload['tool'] == 'run_command'
    assert payload['arguments']['purpose'] == 'test command'
    assert payload['exit_code'] == 0
    assert payload['duration_ms'] >= 0
    assert payload['line_count'] == 2
    assert payload['truncated'] is False
    assert payload['result_included'] is False
    assert final['line_count'] == 2
    assert 'hello' in stream_log
    assert '[stderr] error' in stream_log
    assert 'CREATED FILES' not in stream_log
    queue.close()


def test_run_command_does_not_scan_created_files(tmp_path, monkeypatch):
    queue = install_queue(tmp_path, monkeypatch)
    created_file = tmp_path / 'created.txt'
    result = mod.run_command(
        command=f'"{sys.executable}" -c "from pathlib import Path; Path(r\'{created_file}\').write_text(\'created\')"'
    )
    wait_final(queue, result['execution_id'])
    assert created_file.read_text() == 'created'
    assert 'created_files' not in result
    queue.close()


def test_run_command_optional_conversation_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    queue = install_queue(tmp_path, monkeypatch)
    result = mod.run_command(
        command=f'"{sys.executable}" -c "print(\'visible\')"',
        conversation_id='conv-preview', include_output_in_conversation_log=True,
    )
    wait_final(queue, result['execution_id'])
    payload = json.loads((tmp_path / 'conv-preview.jsonl').read_text().splitlines()[-1])
    assert payload['result_included'] is True
    assert payload['output_preview'] == 'visible'
    queue.close()


def test_run_command_timeout_is_logged_and_kills_child(tmp_path, monkeypatch):
    if os.name == 'nt':
        pytest.skip('POSIX process-group assertion')
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    queue = install_queue(tmp_path, monkeypatch)
    pid_file = tmp_path / 'child.pid'
    child_code = f"import os,time,pathlib; pathlib.Path(r'{pid_file}').write_text(str(os.getpid())); time.sleep(30)"
    parent_code = f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(30)"
    result = mod.run_command(
        command=f'"{sys.executable}" -c {shlex.quote(parent_code)}',
        conversation_id='timeout-test', timeout_seconds=.4,
    )
    final = wait_final(queue, result['execution_id'])
    payload = json.loads((tmp_path / 'timeout-test.jsonl').read_text().splitlines()[-1])
    assert final['status'] == 'timeout'
    assert payload['status'] == 'timeout'
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(.05)
    else:
        pytest.fail(f'child process {child_pid} survived timeout')
    queue.close()
