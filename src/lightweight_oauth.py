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
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / "config" / ".env")

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CLIENTS_FILE = DATA_DIR / "oauth_clients.json"
CODES_FILE = DATA_DIR / "oauth_codes.json"
PRIVATE_KEY_FILE = DATA_DIR / "oauth_private_key.pem"

ISSUER = os.getenv("OAUTH_ISSUER", "https://hull-envision-bunkbed.ngrok-free.dev/oauth")
AUDIENCE = os.getenv("OAUTH_AUDIENCE", "https://mcp.local")
TOKEN_TTL_SECONDS = int(os.getenv("OAUTH_TOKEN_TTL_SECONDS", "31536000"))
AUTO_REGISTER_AUTH_CLIENTS = os.getenv("OAUTH_AUTO_REGISTER_AUTH_CLIENTS", "true").lower() == "true"

app = FastAPI(title="Lightweight MCP OAuth Server")


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
    }


@app.get("/oauth/.well-known/oauth-authorization-server")
@app.get("/oauth/.well-known/openid-configuration")
@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/openid-configuration")
def metadata():
    return oauth_metadata()


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


@app.get("/oauth/authorize")
def authorize(
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
        return JSONResponse({
            "error": "invalid_redirect_uri",
            "redirect_uri": redirect_uri,
            "allowed": allowed,
        }, status_code=400)

    code = secrets.token_urlsafe(32)
    codes = load_codes()

    codes[code] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope or "openid profile email",
        "audience": audience or AUDIENCE,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "created_at": time.time(),
    }
    save_codes(codes)

    params = {"code": code}

    if state:
        params["state"] = state

    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}")


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
