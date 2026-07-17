import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_conversation_start_generates_id(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    result = mod.conversation_start()
    assert result['conversation_id'].startswith('conv_')
    assert Path(result['log_path']).exists()


def test_conversation_note_appends_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    mod.conversation_start(conversation_id='safe-id')
    mod.conversation_note('safe-id', 'plan', 'Implement logging')

    payload = json.loads((tmp_path / 'safe-id.jsonl').read_text().splitlines()[-1])
    assert payload['kind'] == 'plan'
    assert payload['content'] == 'Implement logging'


def test_conversation_start_never_uses_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError('subprocess.run must not be called')

    monkeypatch.setattr(mod.subprocess, 'run', fail_if_called)

    result = mod.conversation_start(conversation_id='safe-id')

    assert result['startup_browser_assist']['action'] == 'disabled'
    assert result['startup_browser_assist']['opened_new_tab'] is False


def test_browser_assist_stays_disabled_even_when_legacy_flag_is_true(monkeypatch):
    monkeypatch.setattr(mod, 'CHATGPT_STARTUP_BROWSER_ASSIST', True)

    def fail_if_called(*args, **kwargs):
        raise AssertionError('subprocess.run must not be called')

    monkeypatch.setattr(mod.subprocess, 'run', fail_if_called)
    result = mod.chatgpt_startup_browser_assist()

    assert result['action'] == 'disabled'
    assert result['enabled'] is False

def test_sanitize_blocks_path_escape():
    value = mod.sanitize_conversation_id('../../etc/passwd')
    assert '..' not in value
    assert '/' not in value
