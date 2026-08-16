from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.realtime_calls import RealtimeCallStore
from src import realtime_web


def test_realtime_page_requires_login(tmp_path):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    response = TestClient(app).get("/rt")
    assert response.status_code == 200
    assert "Authenticate to inspect" in response.text
    assert "realtime" not in response.text.lower()


def test_authenticated_realtime_page_uses_split_inspector(tmp_path, monkeypatch):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    monkeypatch.setattr(realtime_web, "_authenticated", lambda request: True)
    response = TestClient(app).get("/rt")
    assert response.status_code == 200
    assert 'class="inspector"' in response.text
    assert "<dialog" not in response.text
    assert "<h1>Real-time calls</h1>" not in response.text
    assert '<div class="view-title">Real-time calls</div>' in response.text
    assert 'id="thinking-toggle" class="pressed"' in response.text
    assert 'class="search-icon"' in response.text


def test_realtime_assets_are_authenticated(tmp_path, monkeypatch):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    client = TestClient(app)
    assert client.get("/rt/assets/trajectory.js").status_code == 401
    monkeypatch.setattr(realtime_web, "_authenticated", lambda request: True)
    script = client.get("/rt/assets/trajectory.js")
    assert script.status_code == 200
    assert "range.start - domainStart" in script.text
    assert "parent_execution_id" in script.text
    assert "state.tab = 'summary'" not in script.text
    assert "THINKING_MIN_MS = 250" in script.text
    assert ".filter(matches)" in script.text
    assert "const start = timing(left).end" in script.text
    assert '<h3>Timing ›</h3>' in script.text
    assert 'class="badge-icon"' in script.text
    assert '<span>${formatDuration(range.duration)}</span>' in script.text

    stylesheet = client.get("/rt/assets/trajectory.css")
    assert "prefers-color-scheme: dark" in stylesheet.text
    assert "@media (max-width: 850px)" in stylesheet.text
    assert ".inspector { position: absolute; z-index: 10; inset: 0; width: 100%" in stylesheet.text
    assert ".badge-label { display: none; }" in stylesheet.text
    assert ".row-time { display: flex; flex-direction: column" in stylesheet.text


def test_realtime_icon_is_served_from_gate_assets(tmp_path, monkeypatch):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    monkeypatch.setattr(realtime_web, "_authenticated", lambda request: True)
    response = TestClient(app).get("/rt/assets/gate.svg")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"


def test_realtime_api_requires_authentication(tmp_path):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    response = TestClient(app).get("/rt/api/calls")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_realtime_api_returns_trajectory_snapshot_when_authenticated(tmp_path, monkeypatch):
    store = RealtimeCallStore()
    store.update({"execution_id": "x1", "status": "success", "tool": "read", "command": "echo ok"})
    app = FastAPI()
    realtime_web.register_realtime_routes(app, store, tmp_path)
    monkeypatch.setattr(realtime_web, "_authenticated", lambda request: True)
    response = TestClient(app).get("/rt/api/calls")
    assert response.status_code == 200
    assert response.json()["calls"][0]["execution_id"] == "x1"
