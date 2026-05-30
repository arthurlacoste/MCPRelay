import os
import sys

import pytest

from agent_manager.manager import AgentManager
from agent_manager.models import AGENT_STATUS_CANCELLED, AGENT_STATUS_FAILED, AGENT_STATUS_RUNNING, AgentSpec


def make_manager(tmp_path, **kwargs):
    return AgentManager(
        tmp_path,
        cwd_allowlist=[str(tmp_path)],
        max_running_agents=kwargs.pop("max_running_agents", 2),
        **kwargs,
    )


def test_agent_manager_submit_returns_queued(tmp_path):
    manager = make_manager(tmp_path)

    result = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path), purpose="unit"))

    assert result["ok"] is True
    assert result["status"] == "queued"
    assert result["position"] == 1


def test_agent_manager_scheduler_respects_max_running_agents(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, max_running_agents=1)
    first = manager.submit(AgentSpec(prompt="one", cwd=str(tmp_path)))["agent_id"]
    second = manager.submit(AgentSpec(prompt="two", cwd=str(tmp_path)))["agent_id"]
    launched = []

    def fake_launch(record):
        launched.append(record.agent_id)
        manager.store.update_status(record.agent_id, AGENT_STATUS_RUNNING, pid=123, heartbeat=True, started=True)

    monkeypatch.setattr(manager, "launch_record", fake_launch)

    manager.scheduler_tick()

    assert launched == [first]
    assert manager.store.get_agent(second).status == "queued"


def test_agent_manager_scheduler_runs_same_cwd_in_parallel_by_default(monkeypatch, tmp_path):
    manager = make_manager(tmp_path, max_running_agents=5)
    agent_ids = [
        manager.submit(AgentSpec(prompt=f"agent {index}", cwd=str(tmp_path)))["agent_id"]
        for index in range(5)
    ]
    launched = []

    def fake_launch(record):
        launched.append(record.agent_id)
        manager.store.update_status(record.agent_id, AGENT_STATUS_RUNNING, pid=123 + len(launched), heartbeat=True, started=True)

    monkeypatch.setattr(manager, "launch_record", fake_launch)

    manager.scheduler_tick()

    assert launched == agent_ids


def test_agent_manager_launch_sets_pythonpath_for_runner(monkeypatch, tmp_path):
    manager = make_manager(tmp_path)
    record = manager.store.create_agent("agt_test", AgentSpec(prompt="hello", cwd=str(tmp_path)))
    popen_calls = {}

    class FakeProcess:
        pid = 12345

    def fake_popen(cmd, stdout, stderr, cwd, close_fds, env):
        popen_calls.update({"cmd": cmd, "cwd": cwd, "env": env})
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    manager.launch_record(record)

    assert popen_calls["cmd"][:3] == [sys.executable, "-m", "agent_manager.runner"]
    assert str(manager.src_dir) in popen_calls["env"]["PYTHONPATH"].split(os.pathsep)


def test_agent_manager_marks_dead_running_process_failed(monkeypatch, tmp_path):
    manager = make_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]
    manager.store.update_status(agent_id, AGENT_STATUS_RUNNING, pid=999999, heartbeat=True, started=True)
    stderr_path = manager.store.run_dir(agent_id) / "stderr.log"
    stderr_path.write_text("runner import failed\n", encoding="utf-8")
    monkeypatch.setattr(manager, "_pid_exists", lambda pid: False)

    manager.scheduler_tick()

    record = manager.store.get_agent(agent_id)
    assert record.status == AGENT_STATUS_FAILED
    assert record.error == "runner import failed"


def test_agent_manager_retry_clones_failed_agent(tmp_path):
    manager = make_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path), conversation_id="conv1"))["agent_id"]
    manager.store.update_status(agent_id, AGENT_STATUS_FAILED, error="boom", completed=True)

    retry = manager.retry(agent_id)

    assert retry["parent_id"] == agent_id
    child = manager.store.get_agent(retry["agent_id"])
    assert child.prompt == "hello"
    assert child.conversation_id == "conv1"


def test_agent_manager_update_refuses_running_agent(tmp_path):
    manager = make_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]
    manager.store.update_status(agent_id, AGENT_STATUS_RUNNING, pid=123, heartbeat=True, started=True)

    with pytest.raises(RuntimeError, match="cannot update a running agent"):
        manager.update(agent_id, prompt="updated")


def test_agent_manager_cancel_marks_queued_agent_cancelled(tmp_path):
    manager = make_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]

    result = manager.cancel(agent_id)

    assert result["status"] == AGENT_STATUS_CANCELLED
    assert manager.store.get_agent(agent_id).status == AGENT_STATUS_CANCELLED


def test_agent_manager_rejects_cwd_outside_allowlist(tmp_path):
    manager = make_manager(tmp_path)

    with pytest.raises(ValueError, match="cwd is outside allowed paths"):
        manager.submit(AgentSpec(prompt="hello", cwd="/tmp"))


def test_agent_manager_preserves_provider_on_retry(tmp_path):
    manager = make_manager(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path), provider="ollama"))["agent_id"]
    manager.store.update_status(agent_id, AGENT_STATUS_FAILED, error="boom", completed=True)

    retry = manager.retry(agent_id)

    child = manager.store.get_agent(retry["agent_id"])
    assert child.provider == "ollama"
