import shutil
import subprocess
import time

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.realtime_calls import RealtimeCallStore
from src import realtime_web


def bearer_request(token: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/rt/api/calls",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })


def test_realtime_page_requires_login(tmp_path):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)
    response = TestClient(app).get("/rt")
    assert response.status_code == 200
    assert "Authenticate to inspect" in response.text
    assert "realtime" not in response.text.lower()
    assert "Authorize Gate" not in response.text


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
    assert 'id="scroll-bottom"' in response.text
    assert 'id="mobile-buckets"' in response.text
    assert 'id="conversation-drawer"' in response.text
    assert 'M21 12a9 9 0 1 1-2.64-6.36L21 8' in response.text


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
    assert "function extendRunCommandsThroughStateCalls(calls)" in script.text
    assert "function resolveStateParent(call, context)" in script.text
    assert "eligible.length === 1 ? eligible[0].execution_id : null" in script.text
    assert "duration_ms: end - range.start" in script.text
    assert '<h3>Timing ›</h3>' in script.text
    assert '<h3>Fields ›</h3>' in script.text
    assert "detailValue(call, 'payload'" in script.text
    assert "detailCache = new Map()" in script.text
    assert "async function loadDetail(call)" in script.text
    assert "function directoryLabel(path)" in script.text
    assert "call.working_directory" in script.text
    assert "let coveredUntil = timing(coveredBy).end" in script.text
    assert "const occupiedUntil = [[], [], []]" in script.text
    assert "const timelineWidth = Math.max(1, host.clientWidth)" in script.text
    assert "const renderedWidth = Math.max(1" in script.text
    assert "occupiedUntil[callLane].findIndex(end => end <= renderedStart)" in script.text
    assert "call.kind === 'thinking' ? 2 : 1" in script.text
    assert "width:max(1px" in script.text
    assert 'class="badge-icon"' in script.text
    assert '<span>${formatDuration(range.duration)}</span>' in script.text
    assert "pendingBottomScroll: true" in script.text
    assert "ledger.scrollTop = ledger.scrollHeight" in script.text
    assert "function updateScrollBottomButton()" in script.text
    assert "scrollTo({ top: $('#ledger').scrollHeight, behavior: 'smooth' })" in script.text
    assert "function toggleConversationDrawer()" in script.text
    assert "$('#mobile-search').addEventListener('click'" in script.text
    assert "const timelineObserver = new ResizeObserver" in script.text
    assert "timelineObserver.disconnect()" in script.text

    stylesheet = client.get("/rt/assets/trajectory.css")
    assert "prefers-color-scheme: dark" in stylesheet.text
    assert "@media (max-width: 850px)" in stylesheet.text
    assert ".inspector { position: absolute; z-index: 10; inset: 0; width: 100%" in stylesheet.text
    assert ".badge-label { display: none; }" in stylesheet.text
    assert ".row-time { display: flex; flex-direction: column" in stylesheet.text
    assert ".ledger.compact .row { grid-template-columns: 90px minmax(180px, 1fr) 100px" in stylesheet.text
    assert ".ledger.compact .row { grid-template-columns: 26px minmax(120px, 1fr) 72px" in stylesheet.text
    assert ".sidebar { position: relative; z-index: 20; display: flex; flex: 0 0 58px" in stylesheet.text
    assert ".sidebar.drawer-open .conversation-drawer { transform: translateX(0); }" in stylesheet.text


def test_realtime_ui_behavior_with_node():
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("Node.js is unavailable")
    result = subprocess.run(
        [node, "tests/realtime_ui_behavior.test.js"],
        cwd=realtime_web.UI_DIR.parent.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "realtime UI behavior: ok"


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


def test_realtime_auth_rejects_regular_mcp_token_scope():
    import lightweight_oauth

    now = int(time.time())
    regular_token = jwt.encode(
        {
            "iss": lightweight_oauth.ISSUER,
            "sub": "local-user",
            "aud": lightweight_oauth.AUDIENCE,
            "iat": now,
            "exp": now + 3600,
            "scope": "openid profile email",
        },
        lightweight_oauth.private_key,
        algorithm="RS256",
        headers={"kid": lightweight_oauth.KID},
    )

    assert realtime_web._authenticated(bearer_request(regular_token)) is False
    assert realtime_web._authenticated(bearer_request(realtime_web._session_token())) is True


def test_realtime_login_rejects_oversized_body_before_form_parsing(tmp_path):
    app = FastAPI()
    realtime_web.register_realtime_routes(app, RealtimeCallStore(), tmp_path)

    response = TestClient(app).post(
        "/rt/login",
        content=b"secret=" + b"x" * (realtime_web.MAX_LOGIN_BODY_BYTES + 1),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_realtime_api_returns_trajectory_snapshot_when_authenticated(tmp_path, monkeypatch):
    store = RealtimeCallStore()
    store.update({
        "execution_id": "x1", "status": "success", "tool": "read", "command": "echo ok",
        "payload": {"query": "test"}, "result": {"ok": True}, "fields": {"query": "test"},
    })
    app = FastAPI()
    realtime_web.register_realtime_routes(app, store, tmp_path)
    monkeypatch.setattr(realtime_web, "_authenticated", lambda request: True)
    response = TestClient(app).get("/rt/api/calls")
    assert response.status_code == 200
    summary = response.json()["calls"][0]
    assert summary["execution_id"] == "x1"
    assert {"command", "payload", "result", "fields"}.isdisjoint(summary)

    detail = TestClient(app).get("/rt/api/calls/x1")
    assert detail.status_code == 200
    assert detail.json()["command"] == "echo ok"
    assert '"query": "test"' in detail.json()["payload"]

    missing = TestClient(app).get("/rt/api/calls/missing")
    assert missing.status_code == 404
