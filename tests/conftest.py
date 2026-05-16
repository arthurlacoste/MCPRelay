"""
Shared fixtures for MCP gateway & OAuth tests.

Sets environment variables before importing the OAuth module, then
patches data-file paths to a temporary directory so tests never
touch real data.
"""

import os
import sys
import tempfile
from pathlib import Path
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient

# -------------------------------------------------------------------
# 1.  Set environment before any application code is imported.
# -------------------------------------------------------------------
os.environ.setdefault("OAUTH_ISSUER", "https://test.local/oauth")
os.environ.setdefault("OAUTH_AUDIENCE", "https://test.local/mcp")
os.environ.setdefault("OAUTH_KEY_ID", "test-key-id")
os.environ.setdefault("OAUTH_TOKEN_TTL_SECONDS", "3600")
os.environ.setdefault("OAUTH_AUTO_REGISTER_AUTH_CLIENTS", "true")

# -------------------------------------------------------------------
# 2.  Import the OAuth FastAPI app.
# -------------------------------------------------------------------
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

import lightweight_oauth as oauth_mod


# -------------------------------------------------------------------
# 3.  Fixtures
# -------------------------------------------------------------------

@pytest.fixture
def oauth_client() -> TestClient:
    """FastAPI TestClient wired to the lightweight OAuth server."""
    return TestClient(oauth_mod.app)


@pytest.fixture
def temp_data_dir(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Patch *oauth_clients.json* and *oauth_codes.json* so each test
    starts with empty, isolated data files.  A fresh RSA key is also
    generated for the test session."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        clients_file = tmp / "oauth_clients.json"
        codes_file = tmp / "oauth_codes.json"
        key_file = tmp / "oauth_private_key.pem"

        clients_file.write_text("{}")
        codes_file.write_text("{}")

        monkeypatch.setattr(oauth_mod, "CLIENTS_FILE", clients_file)
        monkeypatch.setattr(oauth_mod, "CODES_FILE", codes_file)
        monkeypatch.setattr(oauth_mod, "PRIVATE_KEY_FILE", key_file)
        monkeypatch.setattr(oauth_mod, "DATA_DIR", tmp)

        # Re-load the private key so it lives in the temp location
        oauth_mod.private_key = oauth_mod.load_private_key()
        oauth_mod.public_key = oauth_mod.private_key.public_key()

        yield tmp


@pytest.fixture
def registered_client(oauth_client: TestClient,
                       temp_data_dir: Path) -> dict:
    """Register an OAuth client and return its credentials."""
    resp = oauth_client.post("/oauth/register", json={
        "redirect_uris": ["https://client.example/cb"],
        "client_name": "Test Client",
    })
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture
def authorization_code(oauth_client: TestClient,
                        registered_client: dict) -> str:
    """Perform the authorization step and return the *code* query param."""
    resp = oauth_client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered_client["client_id"],
            "redirect_uri": "https://client.example/cb",
            "state": "xyz",
            "scope": "openid profile email",
        },
        follow_redirects=False,
    )
    # Starlette's RedirectResponse may return 302 or 307
    assert resp.status_code in (302, 307), f"Expected redirect, got {resp.status_code}"
    location = resp.headers["location"]
    assert "code=" in location
    code = location.split("code=")[1].split("&")[0]
    return code


@pytest.fixture
def access_token(oauth_client: TestClient,
                  registered_client: dict,
                  authorization_code: str) -> str:
    """Exchange an authorization code for a full token response.

    Returns the *access_token* JWT string.
    """
    resp = oauth_client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": "https://client.example/cb",
            "client_id": registered_client["client_id"],
            "client_secret": registered_client.get("client_secret") or "",
        },
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]
