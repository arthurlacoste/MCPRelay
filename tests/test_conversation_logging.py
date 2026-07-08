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


def test_conversation_start_does_not_use_browser_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path)
    monkeypatch.setattr(mod, 'CHATGPT_STARTUP_BROWSER_ASSIST', False)

    def fail_if_called(*args, **kwargs):
        raise AssertionError('subprocess.run must not be called')

    monkeypatch.setattr(mod.subprocess, 'run', fail_if_called)

    result = asyncio.run(mod.conversation_start(conversation_id='safe-id'))

    assert result['startup_browser_assist']['action'] == 'disabled'
    assert result['startup_browser_assist']['opened_new_tab'] is False


def test_browser_assist_opt_in_uses_script_runner(monkeypatch):
    monkeypatch.setattr(mod, 'CHATGPT_STARTUP_BROWSER_ASSIST', True)

    class Completed:
        returncode = 0
        stdout = 'opened_new\n'
        stderr = ''

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(mod.subprocess, 'run', fake_run)

    result = mod.chatgpt_startup_browser_assist()

    assert calls
    assert calls[0][0][0][0] == 'osascript'
    assert result['action'] == 'opened_new'
    assert result['opened_new_tab'] is True


def test_sanitize_blocks_path_escape():
    value = mod.sanitize_conversation_id('../../etc/passwd')
    assert '..' not in value
    assert '/' not in value
