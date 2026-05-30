from fastapi.testclient import TestClient

from agent_manager.manager import AgentManager
from agent_manager.models import AgentSpec
from agent_manager.web import create_agents_app


def make_client(tmp_path):
    manager = AgentManager(tmp_path, cwd_allowlist=[str(tmp_path)])
    client = TestClient(create_agents_app(manager))
    return client, manager


def test_agents_web_list_returns_html_table(tmp_path):
    client, manager = make_client(tmp_path)
    manager.submit(AgentSpec(prompt="hello", purpose="unit", cwd=str(tmp_path)))

    response = client.get("/")

    assert response.status_code == 200
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in response.text
    assert "agent-card" in response.text
    assert "Running" in response.text
    assert "@media (max-width: 760px)" in response.text
    assert ".agent-grid { grid-template-columns: 1fr; }" in response.text
    assert ".btn, button { width: 100%;" in response.text
    assert "setInterval(refreshAgents, 3000)" in response.text


def test_agents_web_list_partial_returns_refresh_fragments(tmp_path):
    client, manager = make_client(tmp_path)
    manager.submit(AgentSpec(prompt="hello", purpose="unit", cwd=str(tmp_path)))

    response = client.get("/?partial=1")

    assert response.status_code == 200
    assert "template id='stats'" in response.text
    assert "template id='cards'" in response.text
    assert "agent-card" in response.text


def test_agents_web_detail_returns_prompt_and_status(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", purpose="unit", cwd=str(tmp_path)))["agent_id"]

    response = client.get(f"/{agent_id}")

    assert response.status_code == 200
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in response.text
    assert ".detail-grid { grid-template-columns: 1fr; }" in response.text
    assert "hello" in response.text
    assert "queued" in response.text
    assert "[redacted]" not in response.text


def test_agents_web_detail_shows_completed_result(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", purpose="unit", cwd=str(tmp_path)))["agent_id"]
    manager.store.write_json(agent_id, "result.json", {"ok": True, "stdout": "done\n"})

    response = client.get(f"/{agent_id}")

    assert response.status_code == 200
    assert "&quot;stdout&quot;: &quot;done\\n&quot;" in response.text
    assert "done" in response.text


def test_agents_web_live_returns_latest_output_and_result(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", purpose="unit", cwd=str(tmp_path)))["agent_id"]
    run_dir = manager.store.run_dir(agent_id)
    (run_dir / "stdout.log").write_text("first\nsecond\n", encoding="utf-8")
    (run_dir / "stderr.log").write_text("warn\n", encoding="utf-8")
    manager.store.write_json(agent_id, "result.json", {"ok": True, "stdout": "second\n"})

    response = client.get(f"/{agent_id}/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_running"] is True
    assert payload["logs"]["stdout"] == "first\nsecond"
    assert payload["logs"]["stderr"] == "warn"
    assert '"stdout": "second\\n"' in payload["result"]


def test_agents_web_retry_creates_child_agent(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]

    response = client.post(f"/{agent_id}/retry", follow_redirects=False)

    assert response.status_code == 303
    children = [record for record in manager.store.list_agents(limit=10) if record.parent_id == agent_id]
    assert len(children) == 1


def test_agents_web_update_changes_editable_fields(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]

    response = client.post(
        f"/{agent_id}/update",
        data={"prompt": "updated", "purpose": "unit", "cwd": str(tmp_path)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = manager.store.get_agent(agent_id)
    assert record.prompt == "updated"
    assert record.purpose == "unit"


def test_agents_web_logs_returns_empty_state_instead_of_blank_page(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]

    response = client.get(f"/{agent_id}/logs?stream=stdout")

    assert response.status_code == 200
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in response.text
    assert "white-space: pre-wrap" in response.text
    assert "No stdout lines yet" in response.text
    assert "Agent Logs" in response.text


def test_agents_web_logs_raw_keeps_plain_text_response(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", cwd=str(tmp_path)))["agent_id"]
    (manager.store.run_dir(agent_id) / "stdout.log").write_text("line 1\nline 2\n", encoding="utf-8")

    response = client.get(f"/{agent_id}/logs?stream=stdout&raw=true")

    assert response.status_code == 200
    assert response.text == "line 1\nline 2"


def test_agents_web_detail_and_update_include_provider(tmp_path):
    client, manager = make_client(tmp_path)
    agent_id = manager.submit(AgentSpec(prompt="hello", provider="ollama", cwd=str(tmp_path)))["agent_id"]

    response = client.get(f"/{agent_id}")

    assert response.status_code == 200
    assert "Provider" in response.text
    assert "ollama" in response.text

    update = client.post(
        f"/{agent_id}/update",
        data={"prompt": "hello", "purpose": "unit", "provider": "deepseek", "cwd": str(tmp_path)},
        follow_redirects=False,
    )

    assert update.status_code == 303
    assert manager.store.get_agent(agent_id).provider == "deepseek"
