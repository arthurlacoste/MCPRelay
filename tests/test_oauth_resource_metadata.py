from fastapi.testclient import TestClient

import mcp_gateway
from oauth_resource_metadata import _base_url


def composed_mcp_client(base_url: str) -> TestClient:
    app = mcp_gateway.mcp.http_app(
        path="/mcp",
        middleware=mcp_gateway.GATEWAY_HTTP_MIDDLEWARE,
    )
    return TestClient(app, base_url=base_url)


def test_composed_fastmcp_rfc9728_uses_request_host():
    client = composed_mcp_client("https://mj-1.taildc7e9e.ts.net")

    metadata = client.get("/.well-known/oauth-protected-resource/mcp")
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == "https://mj-1.taildc7e9e.ts.net/mcp"
    assert metadata.json()["authorization_servers"] == [
        "https://mj-1.taildc7e9e.ts.net/oauth"
    ]

    challenge = client.post("/mcp", json={})
    assert challenge.status_code == 401
    assert (
        'resource_metadata="https://mj-1.taildc7e9e.ts.net/'
        '.well-known/oauth-protected-resource/mcp"'
        in challenge.headers["www-authenticate"]
    )
    assert "stale.example" not in challenge.headers["www-authenticate"]


def test_missing_host_uses_static_base_url_fallback():
    assert _base_url(None, "https://stale.example/") == "https://stale.example"
