import asyncio

import mcp_gateway as mod
from agent_manager.manager import AgentManager
from agent_manager.models import AgentSpec


def temp_manager(tmp_path):
    return AgentManager(tmp_path, cwd_allowlist=[str(tmp_path)], max_running_agents=2)


def test_deepseek_agent_submit_logs_started_and_completed(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    events = []
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: events.append((args, kwargs)))

    result = asyncio.run(mod.deepseek_agent_submit(
        prompt="hello",
        conversation_id="conv1",
        purpose="unit",
        cwd=str(tmp_path),
    ))

    assert result["ok"] is True
    assert [event[0][2]["status"] for event in events] == ["started", "completed"]
    assert events[0][0][1] == "deepseek_agent_submit"


def test_deepseek_agent_list_returns_agents(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_list())

    assert len(result["agents"]) == 1


def test_deepseek_agent_get_redacts_secrets(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path), metadata={"api_key": "secret"}))["agent_id"]
    manager.store.write_json(agent_id, "result.json", {"nested": {"secret_token": "abc"}})
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_get(agent_id))

    assert "abc" not in str(result)
    assert "[redacted]" in str(result)
    assert result["agent"]["max_tokens"] == 4000
    assert result["result"]["nested"]["secret_token"] == "[redacted]"


def test_deepseek_agent_get_returns_completed_result(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]
    manager.store.write_json(agent_id, "result.json", {"ok": True, "stdout": "done\n"})
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_get(agent_id))

    assert result["result"] == {"ok": True, "stdout": "done\n"}


def test_deepseek_agent_logs_tails_output(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]
    (manager.store.run_dir(agent_id) / "stdout.log").write_text("a\nb\nc\n", encoding="utf-8")
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_logs(agent_id, tail=2))

    assert result["content"] == "b\nc"


def test_deepseek_agent_retry_preserves_conversation_id(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path), conversation_id="conv1"))["agent_id"]
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_retry(agent_id, purpose="unit"))

    assert manager.store.get_agent(result["agent_id"]).conversation_id == "conv1"


def test_deepseek_agent_submit_accepts_ollama_provider(monkeypatch, tmp_path):
    manager = temp_manager(tmp_path)
    monkeypatch.setattr(mod, "AGENT_MANAGER", manager)
    monkeypatch.setattr(mod, "ensure_conversation_started", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "log_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(mod, "append_tool_conversation_event", lambda *args, **kwargs: None)

    result = asyncio.run(mod.deepseek_agent_submit(
        prompt="hello",
        conversation_id="conv1",
        purpose="unit",
        cwd=str(tmp_path),
        provider="ollama",
    ))

    record = manager.store.get_agent(result["agent_id"])
    assert record.provider == "ollama"
    assert record.model == "ollama/qwen3.5:35b-a3b-coding-nvfp4"
    assert record.api_base == "http://localhost:11434"
