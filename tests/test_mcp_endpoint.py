"""
Connection tests for the MCP gateway HTTP endpoint.

The MCP gateway serves on two URLs:
  - **Local**  → http://localhost:8761/mcp  (when `start_services.py` is running)
  - **Remote** → https://hull-envision-bunkbed.ngrok-free.dev/mcp  (ngrok tunnel)

Tests automatically probe the remote URL first, then fall back to the local
URL.  If neither is reachable the tests are **skipped** so CI / offline usage
won't produce false failures.

Set ``LIVE_MCP_URL`` in the environment to override the probe order.

Usage::

    pytest tests/test_mcp_endpoint.py -v
    LIVE_MCP_URL=http://localhost:8761 pytest tests/test_mcp_endpoint.py -v
"""

import json
import os
import re

import httpx
import pytest

# ---- Configuration -------------------------------------------------
_REMOTE_URL = os.getenv(
    "LIVE_MCP_URL",
    "https://hull-envision-bunkbed.ngrok-free.dev",
)
_LOCAL_URL = "http://localhost:8761"

LIVE_MCP_PATH = "/mcp"

CONNECT_TIMEOUT = 5.0  # seconds


# ---- Helpers -------------------------------------------------------
def _probe(url: str, timeout: float = CONNECT_TIMEOUT) -> bool:
    """Return *True* if the URL is reachable (HTTP 2xx or 401/405)."""
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=False)
        return r.status_code in (
            200, 302, 307, 401, 405,
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError):
        return False


def _resolve_base_url() -> str:
    """Find a running MCP gateway instance.

    Checks in order:
      1. ``LIVE_MCP_URL`` env var (if set)
      2. Local server (``http://localhost:8761``)
      3. Remote ngrok tunnel
    """
    env_url = os.getenv("LIVE_MCP_URL")
    if env_url:
        return env_url.rstrip("/")

    # Prefer local so developers can run tests without the tunnel
    for url in (_LOCAL_URL, _REMOTE_URL):
        if _probe(f"{url}{LIVE_MCP_PATH}"):
            return url

    return _REMOTE_URL  # last resort – tests will skip


def _complete_live_authorization(base_url: str, response: httpx.Response) -> httpx.Response:
    secret = os.getenv("LIVE_OAUTH_ACCESS_SECRET")
    if not secret:
        pytest.skip("LIVE_OAUTH_ACCESS_SECRET is required for the live OAuth flow")
    match = re.search(r'name="request" value="([^"]+)"', response.text)
    assert match, f"Authorization form missing: {response.status_code}"
    return httpx.post(
        f"{base_url}/oauth/authorize",
        data={"request": match.group(1), "secret": secret},
        timeout=CONNECT_TIMEOUT,
        follow_redirects=False,
    )


def _probe_oauth_metadata(url: str) -> dict | None:
    """Fetch OAuth metadata from the given issuer."""
    for path in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    ):
        try:
            r = httpx.get(f"{url}{path}", timeout=CONNECT_TIMEOUT)
            if r.status_code == 200:
                return r.json()
        except httpx.RequestError:
            continue
    return None


# ---- Fixtures ------------------------------------------------------

@pytest.fixture(scope="module")
def mcp_base_url() -> str:
    return _resolve_base_url()


@pytest.fixture(scope="module")
def mcp_is_reachable(mcp_base_url: str) -> bool:
    return _probe(f"{mcp_base_url}{LIVE_MCP_PATH}")


@pytest.fixture(scope="module")
def oauth_is_reachable(mcp_base_url: str) -> bool:
    return _probe(f"{mcp_base_url}/oauth/health")


# ===================================================================
#  Basic reachability
# ===================================================================

class TestEndpointReachability:
    def test_mcp_responds(self, mcp_base_url: str, mcp_is_reachable: bool):
        """HTTP GET on the MCP endpoint — the gateway may return 401/405
        (expected for an OAuth-protected JSON-RPC-only endpoint)."""
        if not mcp_is_reachable:
            pytest.skip("MCP endpoint not reachable")
        url = f"{mcp_base_url}{LIVE_MCP_PATH}"
        resp = httpx.get(url, timeout=CONNECT_TIMEOUT, follow_redirects=False)
        assert resp.status_code in (200, 302, 307, 401, 405), f"Unexpected status: {resp.status_code}"

    def test_oauth_health(self, mcp_base_url: str, mcp_is_reachable: bool):
        """OAuth health endpoint returns ok."""
        if not mcp_is_reachable:
            pytest.skip("MCP endpoint not reachable")
        resp = httpx.get(
            f"{mcp_base_url}/oauth/health",
            timeout=CONNECT_TIMEOUT,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ===================================================================
#  OAuth metadata discovery on the live server
# ===================================================================

class TestLiveOAuthMetadata:
    def test_discovery_returns_metadata(self, mcp_base_url: str,
                                         mcp_is_reachable: bool):
        if not mcp_is_reachable:
            pytest.skip("endpoint not reachable")
        meta = _probe_oauth_metadata(mcp_base_url)
        assert meta is not None, "No OAuth metadata discovered"
        # The issuer field reflects the OAuth server's configured issuer URL,
        # which may differ from the local proxy URL used to reach it
        assert meta["issuer"].endswith("/oauth")
        assert "authorization_endpoint" in meta
        assert "token_endpoint" in meta

    def test_jwks(self, mcp_base_url: str, mcp_is_reachable: bool):
        if not mcp_is_reachable:
            pytest.skip("endpoint not reachable")
        resp = httpx.get(
            f"{mcp_base_url}/oauth/jwks.json",
            timeout=CONNECT_TIMEOUT,
        )
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) >= 1
        assert keys[0]["kty"] == "RSA"


# ===================================================================
#  OAuth full flow against the live server
# ===================================================================

class TestLiveOAuthFlow:
    """Register a client, authorize, and exchange for tokens on the
    live gateway."""

    def test_register_client(self, mcp_base_url: str, mcp_is_reachable: bool):
        if not mcp_is_reachable:
            pytest.skip("endpoint not reachable")
        resp = httpx.post(
            f"{mcp_base_url}/oauth/register",
            json={"redirect_uris": ["https://test-suite.local/cb"],
                   "client_name": "Test Suite"},
            timeout=CONNECT_TIMEOUT,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_id"].startswith("client_")
        assert body["client_secret"].startswith("secret_")

    def test_authorize_and_token_flow(self, mcp_base_url: str,
                                       mcp_is_reachable: bool):
        if not mcp_is_reachable:
            pytest.skip("endpoint not reachable")

        # 1. Register
        reg = httpx.post(
            f"{mcp_base_url}/oauth/register",
            json={"redirect_uris": ["https://e2e-test.local/cb"]},
            timeout=CONNECT_TIMEOUT,
        ).json()

        # 2. Authorize
        auth_resp = httpx.get(
            f"{mcp_base_url}/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": reg["client_id"],
                "redirect_uri": "https://e2e-test.local/cb",
                "state": "e2e-state",
            },
            timeout=CONNECT_TIMEOUT,
            follow_redirects=False,
        )
        auth_resp = _complete_live_authorization(mcp_base_url, auth_resp)
        assert auth_resp.status_code in (302, 307)
        location = auth_resp.headers["location"]
        assert "code=" in location
        code = location.split("code=")[1].split("&")[0]

        # 3. Exchange for tokens
        token_resp = httpx.post(
            f"{mcp_base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://e2e-test.local/cb",
                "client_id": reg["client_id"],
                "client_secret": reg["client_secret"],
            },
            timeout=CONNECT_TIMEOUT,
        )
        assert token_resp.status_code == 200
        tokens = token_resp.json()
        assert "access_token" in tokens
        assert "id_token" in tokens
        assert tokens["token_type"] == "Bearer"


# ===================================================================
#  JSON-RPC MCP communication (if the endpoint allows GET → redirect)
# ===================================================================

class TestJsonRpc:
    """Attempt a JSON-RPC request to list available MCP tools.

    These tests require a valid bearer token obtained via OAuth.
    """

    @pytest.mark.slow
    def test_list_tools_with_token(self, mcp_base_url: str,
                                    mcp_is_reachable: bool):
        """Obtain an access token first, then call *tools/list*."""
        if not mcp_is_reachable:
            pytest.skip("endpoint not reachable")

        # --- Obtain a token ---
        reg = httpx.post(
            f"{mcp_base_url}/oauth/register",
            json={"redirect_uris": ["https://jsonrpc-test.local/cb"]},
            timeout=CONNECT_TIMEOUT,
        ).json()

        auth_resp = httpx.get(
            f"{mcp_base_url}/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": reg["client_id"],
                "redirect_uri": "https://jsonrpc-test.local/cb",
            },
            timeout=CONNECT_TIMEOUT,
            follow_redirects=False,
        )
        auth_resp = _complete_live_authorization(mcp_base_url, auth_resp)
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        token_resp = httpx.post(
            f"{mcp_base_url}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://jsonrpc-test.local/cb",
                "client_id": reg["client_id"],
                "client_secret": reg["client_secret"],
            },
            timeout=CONNECT_TIMEOUT,
        )
        assert token_resp.status_code == 200
        access_token = token_resp.json()["access_token"]

        # --- JSON-RPC call ---
        # The MCP Streamable HTTP transport requires:
        #   1. Obtain a session ID (first POST returns 400 + mcp-session-id)
        #   2. Call ``initialize`` on the session
        #   3. Make the actual method call
        #   4. Responses are returned as SSE ``event: message\ndata: {…}``
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
        }

        def _sse_json(raw: str) -> dict | None:
            """Extract the JSON payload from an SSE ``data:`` line."""
            for line in raw.splitlines():
                if line.startswith("data: "):
                    return json.loads(line[6:])
            return None

        # 1. Obtain a session ID
        warmup = httpx.post(
            f"{mcp_base_url}{LIVE_MCP_PATH}",
            json={"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 0},
            headers=headers,
            timeout=CONNECT_TIMEOUT,
        )
        session_id = warmup.headers.get("mcp-session-id")
        assert session_id is not None, (
            f"No session ID in warmup response ({warmup.status_code})"
        )

        sess_headers = {**headers, "mcp-session-id": session_id}

        # 2. Initialize the session (required by the MCP protocol)
        init = httpx.post(
            f"{mcp_base_url}{LIVE_MCP_PATH}",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "1.0",
                    "capabilities": {},
                    "clientInfo": {"name": "test-suite", "version": "1.0"},
                },
                "id": 1,
            },
            headers=sess_headers,
            timeout=CONNECT_TIMEOUT * 2,
        )
        assert init.status_code == 200
        init_payload = _sse_json(init.text)
        assert init_payload is not None, f"No SSE data in init response: {init.text}"
        assert "result" in init_payload, f"Init failed: {init_payload}"

        # 3. Call tools/list
        jsonrpc_payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": 2,
        }
        resp = httpx.post(
            f"{mcp_base_url}{LIVE_MCP_PATH}",
            json=jsonrpc_payload,
            headers=sess_headers,
            timeout=CONNECT_TIMEOUT * 2,
        )
        assert resp.status_code == 200
        result = _sse_json(resp.text)
        assert result is not None, f"No SSE data in tools/list response: {resp.text}"
        assert "result" in result, f"tools/list error: {result.get('error')}"
        assert "tools" in result["result"], (
            f"tools/list result has no 'tools' key: {result['result']}"
        )
