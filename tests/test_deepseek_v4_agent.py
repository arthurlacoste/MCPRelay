import asyncio
import os
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_deepseek_v4_agent_calls_openinterpreter_in_process(monkeypatch, tmp_path):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {
            'stdout': 'done\n',
            'stderr': '',
            'chat_result': [{'role': 'assistant', 'content': 'done'}],
        }

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: calls.setdefault('event', (args, kwargs)))

    result = asyncio.run(mod.deepseek_v4_agent(
        prompt='Inspect this repository.',
        conversation_id='conv-deepseek',
        purpose='unit test',
        api_key='secret-test-key',
        timeout_seconds=30,
        cwd=str(tmp_path),
    ))

    assert result['ok'] is True
    assert result['model'] == 'openai/deepseek-chat'
    assert result['api_base'] == 'https://api.deepseek.com/v1'
    assert result['stdout'] == 'done\n'
    assert calls['prompt'] == 'Inspect this repository.'
    assert calls['model'] == 'openai/deepseek-chat'
    assert calls['api_base'] == 'https://api.deepseek.com/v1'
    assert calls['api_key'] == 'secret-test-key'
    assert calls['auto_run'] is True
    assert calls['context_window'] == 4096
    assert calls['max_tokens'] == 200
    assert calls['cwd'] == tmp_path.resolve()
    assert 'secret-test-key' not in str(result)
    assert calls['event'][0][1] == 'deepseek_v4_agent'
    assert calls['event'][0][2]['arguments']['purpose'] == 'unit test'


def test_deepseek_v4_agent_allows_model_and_api_base_override(monkeypatch):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {'stdout': '', 'stderr': '', 'chat_result': None}

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_v4_agent(
        prompt='hello',
        model='openrouter/deepseek/deepseek-v4',
        api_base='https://openrouter.ai/api/v1',
        llm_supports_functions=False,
    ))

    assert result['ok'] is True
    assert calls['prompt'] == 'hello'
    assert calls['model'] == 'openrouter/deepseek/deepseek-v4'
    assert calls['api_base'] == 'https://openrouter.ai/api/v1'
    assert calls['llm_supports_functions'] is False


def test_deepseek_v4_agent_uses_openai_api_key_env(monkeypatch):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {'stdout': '', 'stderr': '', 'chat_result': None}

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'openai-env-key')

    result = asyncio.run(mod.deepseek_v4_agent(prompt='hello'))

    assert result['ok'] is True
    assert calls['api_key'] == 'openai-env-key'
    assert 'openai-env-key' not in str(result)


def test_run_openinterpreter_chat_maps_key_for_litellm(monkeypatch, tmp_path):
    class FakeLLM:
        pass

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()

        def chat(self, prompt):
            assert prompt == 'hello'
            assert os.environ['OPENAI_API_KEY'] == 'deepseek-key'
            assert os.environ['DEEPSEEK_API_KEY'] == 'deepseek-key'
            return [{'role': 'assistant', 'content': 'ok'}]

    fake_interpreter = FakeInterpreter()
    fake_module = types.ModuleType('interpreter')
    fake_module.interpreter = fake_interpreter
    monkeypatch.setitem(sys.modules, 'interpreter', fake_module)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)

    result = mod.run_openinterpreter_chat(
        prompt='hello',
        model='openai/deepseek-chat',
        api_base='https://api.deepseek.com/v1',
        api_key='deepseek-key',
        auto_run=True,
        llm_supports_functions=True,
        context_window=4096,
        max_tokens=200,
        cwd=tmp_path,
    )

    assert result['chat_result'] == [{'role': 'assistant', 'content': 'ok'}]
    assert fake_interpreter.llm.model == 'openai/deepseek-chat'
    assert fake_interpreter.llm.api_base == 'https://api.deepseek.com/v1'
    assert fake_interpreter.llm.api_key == 'deepseek-key'
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'DEEPSEEK_API_KEY' not in os.environ


def test_deepseek_v4_agent_reports_missing_openinterpreter(monkeypatch):
    def fake_chat(**kwargs):
        raise RuntimeError('OpenInterpreter is not installed')

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_v4_agent(prompt='hello'))

    assert result['ok'] is False
    assert result['exit_code'] == 1
    assert result['error'] == 'openinterpreter_not_installed'


def test_deepseek_v4_agent_rejects_empty_prompt(monkeypatch):
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)

    try:
        asyncio.run(mod.deepseek_v4_agent(prompt='  '))
    except ValueError as exc:
        assert str(exc) == 'prompt must not be empty'
    else:
        raise AssertionError('expected ValueError')
