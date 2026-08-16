"""Authenticated routes for the Gate realtime trajectory UI."""
from __future__ import annotations

import hashlib
import html
import time
from pathlib import Path

import jwt
from fastapi import Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from realtime_calls import RealtimeCallStore, read_call_log
from request_body_limit import RequestBodyLimitMiddleware

SESSION_COOKIE = "gate_rt_session"
UI_DIR = Path(__file__).resolve().parent / "realtime_ui"
MAX_LOGIN_BODY_BYTES = 4096


def _realtime_page() -> str:
    assets = (UI_DIR / "trajectory.css", UI_DIR / "trajectory.js")
    digest_input = b"".join(
        asset.name.encode("utf-8") + b"\0" + hashlib.sha256(asset.read_bytes()).digest()
        for asset in assets
    )
    digest = hashlib.sha256(digest_input).hexdigest()[:12]
    return (UI_DIR / "index.html").read_text(encoding="utf-8").replace("__ASSET_VERSION__", digest)


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def _authenticated(request: Request) -> bool:
    token = _token_from_request(request)
    if not token:
        return False
    try:
        from lightweight_oauth import AUDIENCE, ISSUER, public_key
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
        )
        return "rt" in str(claims.get("scope") or "").split()
    except (ImportError, jwt.InvalidTokenError, ValueError):
        return False


def _session_token() -> str:
    from lightweight_oauth import AUDIENCE, ISSUER, KID, private_key
    now = int(time.time())
    return jwt.encode(
        {"iss": ISSUER, "sub": "local-user", "aud": AUDIENCE, "iat": now, "exp": now + 3600, "scope": "rt"},
        private_key, algorithm="RS256", headers={"kid": KID},
    )


def _login_page(error: str = "") -> str:
    alert = f'<p class="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gate · Authorize</title>
<style>*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#fbfbfc;color:#17181b;font:14px/1.45 system-ui,sans-serif}}main{{width:min(390px,90vw);text-align:center}}.logo{{font-size:24px;font-weight:800}}.logo span{{padding:4px 6px;border-radius:3px;background:#17181b;color:#fff;font-size:10px;letter-spacing:.08em;vertical-align:middle}}p{{color:#737984}}form{{display:grid;gap:12px;margin-top:26px}}input,button{{padding:13px;border:1px solid #dfe2e8;border-radius:8px;font:inherit}}button{{background:#17181b;color:#fff;cursor:pointer}}.alert{{color:#b42318}}</style></head>
<body><main><div class="logo">gate</div>
<p>Authenticate to inspect Gate activity.</p>{alert}<form method="post" action="/rt/login">
<input name="secret" type="password" autocomplete="current-password" placeholder="Access secret" required autofocus>
<button>Open trajectory</button></form></main></body></html>"""


def register_realtime_routes(app, store: RealtimeCallStore, logs_dir: Path) -> None:
    app.add_middleware(
        RequestBodyLimitMiddleware,
        path="/rt/login",
        max_bytes=MAX_LOGIN_BODY_BYTES,
    )

    @app.get("/rt")
    def realtime_page(request: Request):
        if not _authenticated(request):
            return HTMLResponse(_login_page())
        return HTMLResponse(_realtime_page(), headers={"Cache-Control": "no-cache"})

    @app.get("/rt/assets/{name}")
    def realtime_asset(name: str, request: Request):
        if not _authenticated(request) or name not in {"trajectory.css", "trajectory.js", "gate.svg"}:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if name == "gate.svg":
            return FileResponse(UI_DIR / name, media_type="image/svg+xml")
        media_type = "text/css" if name.endswith(".css") else "text/javascript"
        return FileResponse(
            UI_DIR / name,
            media_type=media_type,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.post("/rt/login", response_class=HTMLResponse)
    def realtime_login(request: Request, secret: str = Form("")):
        from lightweight_oauth import ACCESS_SECRET_HASH, LOGIN_MAX_ATTEMPTS, TRUSTED_PROXY_NETWORKS, access_gate, client_address
        peer = request.client.host if request.client else "unknown"
        address = client_address(peer, request.headers.get("x-forwarded-for", ""), TRUSTED_PROXY_NETWORKS)
        result = access_gate.authenticate(address, LOGIN_MAX_ATTEMPTS, ACCESS_SECRET_HASH, secret)
        if result != "valid":
            return HTMLResponse(_login_page("Invalid access secret."), status_code=401)
        response = RedirectResponse("/rt", status_code=303)
        response.set_cookie(
            SESSION_COOKIE, _session_token(), httponly=True,
            secure=request.url.scheme == "https", samesite="lax", max_age=3600,
        )
        return response

    @app.get("/rt/api/calls")
    def realtime_calls(request: Request):
        if not _authenticated(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return store.summary_snapshot()

    @app.get("/rt/api/calls/{execution_id}")
    def realtime_call(execution_id: str, request: Request):
        if not _authenticated(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        item = store.get_call(execution_id)
        if item is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        return item

    @app.get("/rt/api/calls/{execution_id}/log")
    def realtime_log(execution_id: str, request: Request, offset: int = 0, limit: int = 262144):
        if not _authenticated(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        item = store.get_call(execution_id)
        if not item or not item.get("log_ref"):
            return JSONResponse({"error": "not_found"}, status_code=404)
        return JSONResponse(read_call_log(logs_dir / Path(item["log_ref"]).name, offset, min(limit, 262144)))
