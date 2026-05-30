import asyncio
import io
import os
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_deepseek_v4_agent_calls_openinterpreter_in_process(monkeypatch, tmp_path):
    calls = {}
    events = []

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
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: events.append((args, kwargs)))

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
    assert calls['prompt'].endswith('Inspect this repository.')
    assert calls['model'] == 'openai/deepseek-chat'
    assert calls['api_base'] == 'https://api.deepseek.com/v1'
    assert calls['api_key'] == 'secret-test-key'
    assert calls['auto_run'] is False
    assert calls['context_window'] == 8192
    assert calls['max_tokens'] == 4000
    assert calls['cwd'] == tmp_path.resolve()
    assert 'secret-test-key' not in str(result)
    assert [event[0][2]['status'] for event in events] == ['started', 'completed']
    assert events[0][0][1] == 'deepseek_v4_agent'
    assert events[0][0][2]['arguments']['purpose'] == 'unit test'


def test_deepseek_v4_agent_logs_cancelled_conversation_event(monkeypatch):
    events = []

    async def fake_to_thread(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(mod.asyncio, 'to_thread', fake_to_thread)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: events.append((args, kwargs)))

    try:
        asyncio.run(mod.deepseek_v4_agent(
            prompt='hello',
            conversation_id='conv-cancel',
            purpose='unit test',
            timeout_seconds=30,
        ))
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError('expected CancelledError')

    assert [event[0][2]['status'] for event in events] == ['started', 'cancelled']
    assert events[1][0][0] == 'conv-cancel'
    assert events[1][0][2]['error'] == 'cancelled'


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
        purpose='unit test',
        model='openrouter/deepseek/deepseek-v4',
        api_base='https://openrouter.ai/api/v1',
        llm_supports_functions=False,
    ))

    assert result['ok'] is True
    assert calls['prompt'].endswith('hello')
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

    result = asyncio.run(mod.deepseek_v4_agent(prompt='hello', purpose='unit test'))

    assert result['ok'] is True
    assert calls['api_key'] == 'openai-env-key'
    assert 'openai-env-key' not in str(result)


def test_run_openinterpreter_chat_maps_key_for_litellm(monkeypatch, tmp_path):
    class FakeLLM:
        pass

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()
            self.messages = [{'role': 'assistant', 'content': 'ok'}]
            self.last_messages_count = 0

        def chat(self, prompt, display=True, stream=False):
            assert prompt == 'hello'
            assert display is False
            assert stream is True
            assert os.environ['OPENAI_API_KEY'] == 'deepseek-key'
            assert os.environ['DEEPSEEK_API_KEY'] == 'deepseek-key'
            yield {'role': 'assistant', 'type': 'message', 'content': 'ok'}

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


def test_run_openinterpreter_chat_tees_stdout_and_stderr(monkeypatch, tmp_path):
    class FakeLLM:
        pass

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()
            self.auto_run = None
            self.disable_telemetry = False
            self.messages = [{'role': 'assistant', 'content': 'ok'}]
            self.last_messages_count = 0

        def chat(self, prompt, display=True, stream=False):
            print('live stdout')
            print('live stderr', file=sys.stderr)
            yield {'role': 'assistant', 'type': 'message', 'content': 'streamed answer'}

    fake_module = types.ModuleType('interpreter')
    fake_module.interpreter = FakeInterpreter()
    monkeypatch.setitem(sys.modules, 'interpreter', fake_module)
    stdout_target = io.StringIO()
    stderr_target = io.StringIO()

    result = mod.run_openinterpreter_chat(
        prompt='hello',
        model='openai/deepseek-chat',
        api_base='https://api.deepseek.com/v1',
        api_key=None,
        auto_run=True,
        llm_supports_functions=True,
        context_window=4096,
        max_tokens=200,
        cwd=tmp_path,
        stdout_target=stdout_target,
        stderr_target=stderr_target,
    )

    assert result['stdout'] == 'live stdout\nstreamed answer'
    assert result['stderr'] == 'live stderr\n'
    assert stdout_target.getvalue() == 'live stdout\nstreamed answer'
    assert stderr_target.getvalue() == 'live stderr\n'


def test_deepseek_v4_agent_reports_missing_openinterpreter(monkeypatch):
    def fake_chat(**kwargs):
        raise RuntimeError('OpenInterpreter is not installed')

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_v4_agent(prompt='hello', purpose='unit test'))

    assert result['ok'] is False
    assert result['exit_code'] == 1
    assert result['error'] == 'openinterpreter_not_installed'


def test_deepseek_v4_agent_rejects_empty_prompt(monkeypatch):
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)

    try:
        asyncio.run(mod.deepseek_v4_agent(prompt='  ', purpose='unit test'))
    except ValueError as exc:
        assert str(exc) == 'prompt must not be empty'
    else:
        raise AssertionError('expected ValueError')


def test_deepseek_v4_agent_injects_configurable_preprompt(monkeypatch, tmp_path):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {'stdout': '', 'stderr': '', 'chat_result': None}

    preprompt = tmp_path / 'deepseek_agent_preprompt.md'
    preprompt.write_text('SYSTEM GUIDELINE', encoding='utf-8')

    monkeypatch.setattr(mod, 'DEEPSEEK_AGENT_PREPROMPT_FILE', preprompt)
    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_v4_agent(prompt='Do the task', purpose='unit test'))

    assert result['ok'] is True
    assert calls['prompt'].startswith('SYSTEM GUIDELINE')
    assert '## Mission utilisateur' in calls['prompt']
    assert 'Do the task' in calls['prompt']


def test_deepseek_v4_agent_clamps_requested_limits(monkeypatch):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {'stdout': '', 'stderr': '', 'chat_result': None}

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    original_get_tool_settings = mod.get_tool_settings

    def fake_get_tool_settings(tool_name):
        cfg = original_get_tool_settings(tool_name)
        if tool_name == 'deepseek_v4_agent':
            cfg = dict(cfg)
            cfg.update({
                'hard_max_tokens': 6000,
                'hard_context_window': 16384,
                'hard_timeout_seconds': 1200,
            })
        return cfg

    monkeypatch.setattr(mod, 'get_tool_settings', fake_get_tool_settings)

    result = asyncio.run(mod.deepseek_v4_agent(
        prompt='hello',
        purpose='unit test',
        max_tokens=999999,
        context_window=999999,
        timeout_seconds=999999,
    ))

    assert result['ok'] is True
    assert calls['max_tokens'] == 6000
    assert calls['context_window'] == 16384


def test_deepseek_v4_agent_uses_ollama_defaults(monkeypatch, tmp_path):
    calls = {}

    def fake_chat(**kwargs):
        calls.update(kwargs)
        return {'stdout': 'ok', 'stderr': '', 'chat_result': []}

    monkeypatch.setattr(mod, 'run_openinterpreter_chat', fake_chat)
    monkeypatch.setattr(mod, 'ensure_conversation_started', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'log_action', lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, 'append_tool_conversation_event', lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_v4_agent(
        prompt='hello',
        purpose='unit test',
        provider='ollama',
        cwd=str(tmp_path),
    ))

    assert result['ok'] is True
    assert result['provider'] == 'ollama'
    assert result['model'] == 'ollama/qwen3.5:35b-a3b-coding-nvfp4'
    assert result['api_base'] == 'http://localhost:11434'
    assert calls['provider'] == 'ollama'
    assert calls['api_key'] is None


def test_run_openinterpreter_chat_ollama_does_not_set_deepseek_key(monkeypatch, tmp_path):
    class FakeLLM:
        pass

    class FakeInterpreter:
        def __init__(self):
            self.llm = FakeLLM()
            self.messages = []
            self.last_messages_count = 0

        def chat(self, prompt, display=True, stream=False):
            assert 'DEEPSEEK_API_KEY' not in os.environ
            yield {'role': 'assistant', 'type': 'message', 'content': 'ok'}

    fake_module = types.ModuleType('interpreter')
    fake_module.interpreter = FakeInterpreter()
    monkeypatch.setitem(sys.modules, 'interpreter', fake_module)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)

    result = mod.run_openinterpreter_chat(
        prompt='hello',
        model='ollama/qwen3.5:35b-a3b-coding-nvfp4',
        api_base='http://localhost:11434',
        api_key=None,
        auto_run=True,
        llm_supports_functions=True,
        context_window=4096,
        max_tokens=200,
        cwd=tmp_path,
        provider='ollama',
    )

    assert result['stdout'] == 'ok'
