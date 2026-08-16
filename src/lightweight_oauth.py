#!/usr/bin/env python3

import base64
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from environment_config import gateway_paths, load_gateway_environment
from oauth_access_gate import OAuthAccessGate, client_address, login_page, trusted_proxy_networks
from http_activity_monitor import OAuthActivityMiddleware, set_activity_observer

BASE_DIR = Path(__file__).resolve().parent.parent
load_gateway_environment(BASE_DIR)
GATEWAY_PATHS = gateway_paths(BASE_DIR)

DATA_DIR = GATEWAY_PATHS.data
DATA_DIR.mkdir(exist_ok=True)
CLIENTS_FILE = DATA_DIR / "oauth_clients.json"
CODES_FILE = DATA_DIR / "oauth_codes.json"
PRIVATE_KEY_FILE = DATA_DIR / "oauth_private_key.pem"

ISSUER = os.getenv("OAUTH_ISSUER", "https://hull-envision-bunkbed.ngrok-free.dev/oauth")
AUDIENCE = os.getenv("OAUTH_AUDIENCE", "https://mcp.local")
TOKEN_TTL_SECONDS = int(os.getenv("OAUTH_TOKEN_TTL_SECONDS", "2592000"))
AUTO_REGISTER_AUTH_CLIENTS = os.getenv("OAUTH_AUTO_REGISTER_AUTH_CLIENTS", "true").lower() == "true"
ACCESS_SECRET_HASH = os.getenv("OAUTH_ACCESS_SECRET_HASH", "")
LOGIN_MAX_ATTEMPTS = max(1, int(os.getenv("OAUTH_LOGIN_MAX_ATTEMPTS", "5")))
TRUSTED_PROXY_NETWORKS = trusted_proxy_networks(os.getenv("OAUTH_TRUSTED_PROXY_NETWORKS", ""))

MAX_AUTHORIZATION_BODY_BYTES = 4096



class AuthorizationBodyLimitMiddleware:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/oauth/authorize":
            return await self.application(scope, receive, send)
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            body.extend(message.get("body", b""))
            if len(body) > MAX_AUTHORIZATION_BODY_BYTES:
                response = JSONResponse({"error": "request_too_large"}, status_code=413)
                return await response(scope, receive, send)
            more_body = message.get("more_body", False)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return await self.application(scope, replay, send)


app = FastAPI(title="Lightweight MCP OAuth Server")
app.add_middleware(AuthorizationBodyLimitMiddleware)
app.add_middleware(OAuthActivityMiddleware)
access_gate = OAuthAccessGate()


def load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path: Path, data: dict):
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    tmp_path.replace(path)


def load_private_key():
    if PRIVATE_KEY_FILE.exists():
        with open(PRIVATE_KEY_FILE, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(pem)

    os.chmod(PRIVATE_KEY_FILE, 0o600)

    return key


def load_clients() -> dict:
    return load_json_file(CLIENTS_FILE)


def save_clients(data: dict):
    save_json_file(CLIENTS_FILE, data)


def load_codes() -> dict:
    return load_json_file(CODES_FILE)


def save_codes(data: dict):
    save_json_file(CODES_FILE, data)


private_key = load_private_key()
public_key = private_key.public_key()
KID = os.getenv("OAUTH_KEY_ID", "local-dev-key")


def b64url_int(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def oauth_metadata() -> dict:
    return {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "registration_endpoint": f"{ISSUER}/register",
        "jwks_uri": f"{ISSUER}/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "scopes_supported": ["openid", "profile", "email"],
        # OIDC discovery clients require these when they probe the alias.
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


# RFC 8414 path insertion for issuer https://host/oauth.
@app.get("/.well-known/oauth-authorization-server/oauth")
@app.get("/.well-known/openid-configuration/oauth")
# Legacy aliases retained for existing clients.
@app.get("/oauth/.well-known/oauth-authorization-server")
@app.get("/oauth/.well-known/openid-configuration")
@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/openid-configuration")
def metadata():
    return oauth_metadata()


@app.get("/oauth/assets/vision.webp", include_in_schema=False)
def oauth_vision():
    return FileResponse(
        BASE_DIR / "docs" / "assets" / "vision.webp",
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/oauth/register")
async def register(request: Request):
    data = await request.json()
    client_id = "client_" + secrets.token_urlsafe(16)
    client_secret = "secret_" + secrets.token_urlsafe(32)
    clients = load_clients()

    clients[client_id] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": data.get("redirect_uris", []),
        "client_name": data.get("client_name", "Dynamic MCP Client"),
    }
    save_clients(clients)

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": clients[client_id]["client_name"],
        "redirect_uris": clients[client_id]["redirect_uris"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }


@app.get("/oauth/authorize", response_class=HTMLResponse)
def authorize(
    request: Request,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    state: str | None = None,
    scope: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    audience: str | None = None,
):
    if response_type != "code":
        return JSONResponse({"error": "unsupported_response_type"}, status_code=400)

    clients = load_clients()

    if client_id not in clients:
        if not AUTO_REGISTER_AUTH_CLIENTS:
            return JSONResponse({"error": "invalid_client"}, status_code=400)

        clients[client_id] = {
            "client_id": client_id,
            "client_secret": None,
            "redirect_uris": [redirect_uri],
            "client_name": "Recovered OAuth Client",
        }
        save_clients(clients)

    allowed = clients[client_id].get("redirect_uris", [])

    if redirect_uri not in allowed:
        return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)

    peer = request.client.host if request.client else "unknown"
    source = client_address(peer, request.headers.get("x-forwarded-for", ""), TRUSTED_PROXY_NETWORKS)
    request_id = access_gate.create({
        "client_id": client_id,
        "client_name": clients[client_id].get("client_name", client_id),
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scope or "openid profile email",
        "audience": audience or AUDIENCE,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }, source)
    if not request_id:
        return JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
    return HTMLResponse(login_page(request_id, access_gate.get(request_id).parameters))


@app.post("/oauth/authorize")
def complete_authorization(
    request: Request,
    request_id: str = Form(..., alias="request"),
    secret: str = Form(""),
    decision: str = Form("authorize"),
):
    pending = access_gate.get(request_id)
    if not pending:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if decision == "deny":
        pending = access_gate.consume(request_id)
        query = {"error": "access_denied"}
        if pending.parameters["state"]:
            query["state"] = pending.parameters["state"]
        return RedirectResponse(f'{pending.parameters["redirect_uri"]}?{urlencode(query)}', status_code=302)
    if not ACCESS_SECRET_HASH:
        return JSONResponse({"error": "server_configuration_error"}, status_code=503)
    if len(secret.encode("utf-8")) > 1024:
        return JSONResponse({"error": "invalid_request"}, status_code=413)

    peer = request.client.host if request.client else "unknown"
    address = client_address(peer, request.headers.get("x-forwarded-for", ""), TRUSTED_PROXY_NETWORKS)
    result = access_gate.authenticate(address, LOGIN_MAX_ATTEMPTS, ACCESS_SECRET_HASH, secret)
    if result == "limited":
        return HTMLResponse(
            login_page(request_id, pending.parameters, "Too many attempts. Try again later."),
            status_code=429,
            headers={"Retry-After": "60"},
        )
    if result == "configuration_error":
        return JSONResponse({"error": "server_configuration_error"}, status_code=503)
    if result == "invalid":
        return HTMLResponse(login_page(request_id, pending.parameters, "Invalid access secret."), status_code=401)

    pending = access_gate.consume(request_id)
    if not pending:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    parameters = pending.parameters
    code = secrets.token_urlsafe(32)
    codes = load_codes()
    codes[code] = {
        "client_id": parameters["client_id"],
        "redirect_uri": parameters["redirect_uri"],
        "scope": parameters["scope"],
        "audience": parameters["audience"],
        "code_challenge": parameters["code_challenge"],
        "code_challenge_method": parameters["code_challenge_method"],
        "created_at": time.time(),
    }
    save_codes(codes)
    query = {"code": code}
    if parameters["state"]:
        query["state"] = parameters["state"]
    return RedirectResponse(f'{parameters["redirect_uri"]}?{urlencode(query)}', status_code=302)


@app.post("/oauth/token")
def token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    client_secret: str | None = Form(None),
    code_verifier: str | None = Form(None),
):
    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    clients = load_clients()
    client = clients.get(client_id)

    if not client:
        return JSONResponse({"error": "invalid_client"}, status_code=400)

    if client.get("client_secret") and client_secret and client_secret != client["client_secret"]:
        return JSONResponse({"error": "invalid_client"}, status_code=401)

    codes = load_codes()
    item = codes.pop(code, None)

    if not item:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    save_codes(codes)

    if item["client_id"] != client_id or item["redirect_uri"] != redirect_uri:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)

    if time.time() - item["created_at"] > 300:
        return JSONResponse({"error": "invalid_grant", "error_description": "code expired"}, status_code=400)

    now = int(time.time())

    access_token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "local-user",
            "aud": item["audience"],
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
            "scope": item["scope"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KID},
    )

    id_token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "local-user",
            "aud": client_id,
            "iat": now,
            "exp": now + TOKEN_TTL_SECONDS,
            "email": "local@mcp.dev",
            "name": "Local MCP User",
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KID},
    )

    return {
        "access_token": access_token,
        "id_token": id_token,
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL_SECONDS,
        "scope": item["scope"],
    }


@app.get("/oauth/jwks.json")
def jwks():
    numbers = public_key.public_numbers()

    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "kid": KID,
                "alg": "RS256",
                "n": b64url_int(numbers.n),
                "e": b64url_int(numbers.e),
            }
        ]
    }


@app.get("/oauth/health")
def health():
    return {"ok": True, "issuer": ISSUER, "audience": AUDIENCE}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("OAUTH_PORT", "8762")))
