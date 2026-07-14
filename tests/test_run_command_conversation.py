import json
from pathlib import Path
import sys

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
