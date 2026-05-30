from fastapi.testclient import TestClient

import mcp_gateway as mod


def test_agents_mount_redirects_without_trailing_slash():
    client = TestClient(mod.mcp.http_app(path="/mcp"))

    response = client.get("/agents", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/agents/"


def test_agents_mount_serves_with_trailing_slash():
    client = TestClient(mod.mcp.http_app(path="/mcp"))

    response = client.get("/agents/")

    assert response.status_code == 200
    assert "DeepSeek Operations" in response.text


def test_scheduler_health_endpoint_returns_local_status():
    client = TestClient(mod.mcp.http_app(path="/mcp"))

    response = client.get("/scheduler/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["mode"] == "local"
    assert "scheduler" in payload
    assert "watchdog" in payload
    assert "agents" in payload
    assert "metrics" in payload
