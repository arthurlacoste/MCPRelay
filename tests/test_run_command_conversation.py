import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_snapshot_files_is_platform_independent(tmp_path):
    nested = tmp_path / 'nested'
    nested.mkdir()
    expected = nested / 'example.txt'
    expected.write_text('content')

    assert mod.snapshot_files(tmp_path) == {str(expected)}


def test_run_command_writes_conversation_event(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    monkeypatch.setattr(mod, 'COMMAND_SCAN_ROOT', tmp_path)

    asyncio.run(mod.run_command(
        command='echo hello',
        conversation_id='conv-test',
        purpose='test command'
    ))

    payload = json.loads((tmp_path / 'conv-test.jsonl').read_text().splitlines()[-1])

    assert payload['tool'] == 'run_command'
    assert payload['arguments']['purpose'] == 'test command'
    assert payload['exit_code'] == 0
    assert 'logs/commands/' in payload['result_ref']


def test_run_command_no_output_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'STREAM_DIR', tmp_path)
    monkeypatch.setattr(mod, 'COMMAND_SCAN_ROOT', tmp_path)

    asyncio.run(mod.run_command(
        command='echo hidden',
        conversation_id='conv-hidden'
    ))

    payload = json.loads((tmp_path / 'conv-hidden.jsonl').read_text().splitlines()[-1])
    assert payload['result_included'] is False
