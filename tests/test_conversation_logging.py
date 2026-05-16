import json
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_conversation_start_generates_id(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    result = asyncio.run(mod.conversation_start())
    assert result['conversation_id'].startswith('conv_')
    assert Path(result['log_path']).exists()


def test_conversation_note_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    asyncio.run(mod.conversation_start(conversation_id='safe-id'))
    asyncio.run(mod.conversation_note('safe-id', 'plan', 'Implement logging'))

    payload = json.loads((tmp_path / 'safe-id.jsonl').read_text().splitlines()[-1])
    assert payload['kind'] == 'plan'
    assert payload['content'] == 'Implement logging'


def test_sanitize_blocks_path_escape():
    value = mod.sanitize_conversation_id('../../etc/passwd')
    assert '..' not in value
    assert '/' not in value
