import json
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def allow_conversation_start(monkeypatch):
    original_is_tool_enabled = mod.is_tool_enabled

    def patched_is_tool_enabled(tool_name):
        if tool_name == 'conversation_start':
            return True
        return original_is_tool_enabled(tool_name)

    monkeypatch.setattr(mod, 'is_tool_enabled', patched_is_tool_enabled)


def last_event(path: Path) -> dict:
    return json.loads(path.read_text())['events'][-1]


def test_conversation_start_generates_id(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    allow_conversation_start(monkeypatch)
    result = asyncio.run(mod.conversation_start())
    assert result['conversation_id'].startswith('conv_')
    assert Path(result['log_path']).exists()


def test_conversation_note_appends_json(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    allow_conversation_start(monkeypatch)
    asyncio.run(mod.conversation_start(conversation_id='safe-id'))
    asyncio.run(mod.conversation_note('safe-id', 'plan', 'Implement logging'))

    payload = last_event(tmp_path / 'safe-id.json')
    assert payload['kind'] == 'plan'
    assert payload['content'] == 'Implement logging'


def test_sanitize_blocks_path_escape():
    value = mod.sanitize_conversation_id('../../etc/passwd')
    assert '..' not in value
    assert '/' not in value
