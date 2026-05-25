import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def last_event(path: Path) -> dict:
    return json.loads(path.read_text())['events'][-1]


def test_run_command_writes_conversation_event(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    asyncio.run(mod.run_command(
        command='echo hello',
        conversation_id='conv-test',
        purpose='test command'
    ))

    payload = last_event(tmp_path / 'conv-test.json')

    assert payload['tool'] == 'run_command'
    assert payload['arguments']['purpose'] == 'test command'
    assert payload['exit_code'] == 0
    assert payload['timed_out'] is False
    assert Path(payload['result_ref']).parent == tmp_path


def test_run_command_no_output_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    asyncio.run(mod.run_command(
        command='echo hidden',
        conversation_id='conv-hidden',
        purpose='test command'
    ))

    payload = last_event(tmp_path / 'conv-hidden.json')
    assert payload['result_included'] is False


def test_run_command_result_omits_command_but_keeps_log_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    result = asyncio.run(mod.run_command(
        command='echo visible',
        conversation_id='conv-result',
        purpose='test compact result'
    ))

    assert 'COMMAND:' not in result
    assert 'echo visible' not in result
    assert 'EXIT CODE: 0' in result
    assert 'TIMED OUT: False' in result
    assert f'LOG FILE: {tmp_path}' in result
    assert 'STDOUT:\nvisible' in result

    payload = last_event(tmp_path / 'conv-result.json')
    assert payload['arguments']['command'] == 'echo visible'
    assert Path(payload['result_ref']).parent == tmp_path


def test_run_command_stream_log_keeps_full_command_for_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)

    asyncio.run(mod.run_command(
        command='echo audit',
        conversation_id='conv-audit',
        purpose='test audit trail'
    ))

    payload = last_event(tmp_path / 'conv-audit.json')
    stream_log = Path(payload['result_ref'])

    assert stream_log.read_text().startswith('COMMAND:\necho audit\n\n')
