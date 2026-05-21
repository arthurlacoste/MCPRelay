import asyncio
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_launch_agent_opens_chrome_tab(monkeypatch):
    calls = {}

    def fake_run(args, check, capture_output, text):
        calls['args'] = args
        calls['check'] = check
        calls['capture_output'] = capture_output
        calls['text'] = text
        return subprocess.CompletedProcess(args, 0, stdout='opened_tab\n', stderr='')

    monkeypatch.setattr(mod.subprocess, 'run', fake_run)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda action, payload=None: calls.setdefault('log', (action, payload)))
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: calls.setdefault('event', (args, kwargs)))

    result = asyncio.run(mod.launch_agent(
        agent_url='https://chatgpt.com/g/example-agent',
        conversation_id='conv-launch',
        purpose='unit test',
    ))

    assert result == {
        'ok': True,
        'agent_url': 'https://chatgpt.com/g/example-agent',
        'mode': 'tab',
        'action': 'opened_tab',
        'stderr': '',
    }
    assert calls['args'][0] == 'osascript'
    script = calls['args'][2]
    assert 'tell application "Google Chrome"' in script
    assert 'make new tab' in script
    assert 'https://chatgpt.com/g/example-agent' in script
    assert calls['log'][0] == 'launch_agent'
    assert calls['event'][0][1] == 'launch_agent'


def test_launch_agent_opens_new_window(monkeypatch):
    calls = {}

    def fake_run(args, check, capture_output, text):
        calls['script'] = args[2]
        return subprocess.CompletedProcess(args, 0, stdout='opened_window\n', stderr='')

    monkeypatch.setattr(mod.subprocess, 'run', fake_run)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.launch_agent(
        agent_url='https://example.test/agent',
        new_window=True,
    ))

    assert result['ok'] is True
    assert result['mode'] == 'window'
    assert result['action'] == 'opened_window'
    assert 'set openMode to "window"' in calls['script']
    assert 'make new window' in calls['script']


def test_launch_agent_reports_applescript_error(monkeypatch):
    def fake_run(args, check, capture_output, text):
        return subprocess.CompletedProcess(args, 1, stdout='', stderr='Chrome not available')

    monkeypatch.setattr(mod.subprocess, 'run', fake_run)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.launch_agent(agent_url='https://example.test/agent'))

    assert result['ok'] is False
    assert result['action'] == 'unknown'
    assert result['stderr'] == 'Chrome not available'
