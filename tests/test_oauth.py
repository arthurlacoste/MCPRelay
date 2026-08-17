"""
Unit tests for the lightweight OAuth server (lightweight_oauth.py).

Each test operates on isolated temporary data files so there is no
cross-test pollution.
"""

import time
import hashlib
import base64
import re
import secrets

import jwt
import pytest
from fastapi.testclient import TestClient

import lightweight_oauth as oauth_mod


def complete_authorization(client, response):
    match = re.search(r'name="request" value="([^"]+)"', response.text)
    assert match
    return client.post(
        "/oauth/authorize",
        data={"request": match.group(1), "secret": "correct horse battery staple"},
        follow_redirects=False,
    )


# ===================================================================
#  Metadata & discovery
# ===================================================================

class TestMetadata:
    def test_oauth_authorization_server_well_known(self, oauth_client: TestClient):
        """/.well-known/oauth-authorization-server returns standard fields."""
        resp = oauth_client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        body = resp.json()
        assert body["issuer"] == "https://test.local/oauth"
        assert body["authorization_endpoint"] == "https://test.local/oauth/authorize"
        assert body["token_endpoint"] == "https://test.local/oauth/token"
        assert body["registration_endpoint"] == "https://test.local/oauth/register"
        assert body["jwks_uri"] == "https://test.local/oauth/jwks.json"
        assert "code" in body["response_types_supported"]
        assert "authorization_code" in body["grant_types_supported"]
        assert "S256" in body["code_challenge_methods_supported"]

    def test_issuer_path_rfc8414_alias(self, oauth_client: TestClient):
        resp = oauth_client.get("/.well-known/oauth-authorization-server/oauth")
        assert resp.status_code == 200
        body = resp.json()
        assert body["issuer"] == "https://test.local/oauth"
        assert body["subject_types_supported"] == ["public"]
        assert body["id_token_signing_alg_values_supported"] == ["RS256"]

    def test_openid_configuration_alias(self, oauth_client: TestClient):
        """.well-known/openid-configuration returns the same metadata."""
        r1 = oauth_client.get("/.well-known/oauth-authorization-server")
        r2 = oauth_client.get("/.well-known/openid-configuration")
        assert r1.json() == r2.json()

    def test_issuer_path_openid_configuration_alias(self, oauth_client: TestClient):
        r1 = oauth_client.get("/.well-known/oauth-authorization-server/oauth")
        r2 = oauth_client.get("/.well-known/openid-configuration/oauth")
        assert r2.status_code == 200
        assert r2.json() == r1.json()

    def test_health(self, oauth_client: TestClient):
        resp = oauth_client.get("/oauth/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestHostRelativeIssuer:
    def test_metadata_uses_request_host(self):
        """The issuer and registration endpoint follow the Host header, so a
        tunnel host (e.g. Tailscale) works even when the configured issuer is
        stale or belongs to another tunnel provider."""
        client = TestClient(oauth_mod.app, base_url="https://mj-1.taildc7e9e.ts.net")
        body = client.get("/.well-known/oauth-authorization-server").json()
        assert body["issuer"] == "https://mj-1.taildc7e9e.ts.net/oauth"
        assert body["registration_endpoint"] == "https://mj-1.taildc7e9e.ts.net/oauth/register"
        assert body["token_endpoint"] == "https://mj-1.taildc7e9e.ts.net/oauth/token"
        assert body["jwks_uri"] == "https://mj-1.taildc7e9e.ts.net/oauth/jwks.json"

    def test_protected_resource_metadata(self):
        client = TestClient(oauth_mod.app, base_url="https://mj-1.taildc7e9e.ts.net")
        body = client.get("/.well-known/oauth-protected-resource").json()
        assert body["resource"] == "https://mj-1.taildc7e9e.ts.net/mcp"
        assert body["authorization_servers"] == ["https://mj-1.taildc7e9e.ts.net/oauth"]

    def test_token_iss_follows_request_host(self, oauth_client: TestClient,
                                            registered_client: dict,
                                            temp_data_dir):
        from fastapi.testclient import TestClient as TC
        host_client = TC(oauth_mod.app, base_url="https://mj-1.taildc7e9e.ts.net")
        auth_resp = complete_authorization(host_client, host_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
            },
            follow_redirects=False,
        ))
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]
        resp = host_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.status_code == 200
        access = jwt.decode(
            resp.json()["access_token"],
            options={"verify_signature": False},
        )
        assert access["iss"] == "https://mj-1.taildc7e9e.ts.net/oauth"

        # Decode and verify the id_token issuer
        id_token = jwt.decode(
            resp.json()["id_token"],
            options={"verify_signature": False},
        )
        assert id_token["iss"] == "https://mj-1.taildc7e9e.ts.net/oauth"

    def test_verifier_accepts_host_relative_token(self, temp_data_dir):
        """The MCP JWTVerifier validates host-derived tokens (signature from our
        own public key, audience match) without a fixed issuer."""
        import asyncio
        import time as _time
        from fastmcp.server.auth.providers.jwt import JWTVerifier
        import lightweight_oauth as oauth_mod

        now = int(_time.time())
        token = jwt.encode(
            {
                "iss": "https://mj-1.taildc7e9e.ts.net/oauth",
                "sub": "local-user",
                "aud": "https://test.local/mcp",
                "iat": now,
                "exp": now + 3600,
                "scope": "openid profile email",
            },
            oauth_mod.private_key,
            algorithm="RS256",
            headers={"kid": oauth_mod.KID},
        )

        verifier = JWTVerifier(
            public_key=oauth_mod.public_key_pem(),
            issuer=None,
            audience="https://test.local/mcp",
        )

        async def _verify():
            return await verifier.verify_token(token)

        verified = asyncio.run(_verify())
        assert verified is not None
        assert verified.client_id == "local-user"


# ===================================================================
#  Client registration
# ===================================================================

class TestClientRegistration:
    def test_register_minimal(self, oauth_client: TestClient, temp_data_dir):
        resp = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://app.example/cb"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_id"].startswith("client_")
        assert body["client_secret"].startswith("secret_")
        assert body["redirect_uris"] == ["https://app.example/cb"]
        assert body["client_name"] == "Dynamic MCP Client"
        assert body["grant_types"] == ["authorization_code"]
        assert body["token_endpoint_auth_method"] == "client_secret_post"

    def test_register_with_name(self, oauth_client: TestClient, temp_data_dir):
        resp = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://myapp.example/cb"],
            "client_name": "My App",
        })
        assert resp.status_code == 200
        assert resp.json()["client_name"] == "My App"

    def test_register_persists(self, oauth_client: TestClient, temp_data_dir):
        """Registered clients survive across requests."""
        reg = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://persist.example/cb"],
        }).json()

        # Re-authorize with the same client (no auto-register needed)
        resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": reg["client_id"],
                "redirect_uri": "https://persist.example/cb",
            },
            follow_redirects=False,
        ))
        assert resp.status_code in (302, 307)


# ===================================================================
#  Authorization endpoint
# ===================================================================

class TestAuthorize:
    def test_success(self, oauth_client: TestClient, registered_client: dict):
        resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
                "state": "my-state",
                "scope": "openid profile",
            },
            follow_redirects=False,
        ))
        assert resp.status_code in (302, 307)
        location = resp.headers["location"]
        assert location.startswith("https://client.example/cb?")
        assert "code=" in location
        assert "state=my-state" in location

    def test_auto_register_unknown_client(self, oauth_client: TestClient,
                                           temp_data_dir):
        """When AUTO_REGISTER_AUTH_CLIENTS is true, unknown clients are
        auto-created during authorization."""
        client_id = "client_auto_reg_test_123"
        resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://new-client.example/cb",
                "state": "s1",
            },
            follow_redirects=False,
        ))
        assert resp.status_code in (302, 307)
        assert "code=" in resp.headers["location"]

    def test_invalid_redirect_uri(self, oauth_client: TestClient,
                                   registered_client: dict):
        resp = oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://evil.example/cb",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "invalid_redirect_uri"

    def test_unsupported_response_type(self, oauth_client: TestClient,
                                        registered_client: dict):
        resp = oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "token",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "unsupported_response_type"

    def test_with_pkce_challenge(self, oauth_client: TestClient,
                                  registered_client: dict):
        """Authorization succeeds when a code_challenge is supplied."""
        resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
                "code_challenge": "abc123",
                "code_challenge_method": "plain",
                "state": "pkce-state",
            },
            follow_redirects=False,
        ))
        assert resp.status_code in (302, 307)
        assert "code=" in resp.headers["location"]


# ===================================================================
#  Token endpoint
# ===================================================================

class TestToken:
    def test_success(self, oauth_client: TestClient, registered_client: dict,
                     authorization_code: str):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 3600
        assert "access_token" in body
        assert "id_token" in body
        assert "openid" in body["scope"]

        # Decode and verify the access token
        access = jwt.decode(
            body["access_token"],
            options={"verify_signature": False},
        )
        assert access["iss"] == "https://test.local/oauth"
        assert access["aud"] == "https://test.local/mcp"
        assert access["sub"] == "local-user"

        # Decode and verify the id_token
        ident = jwt.decode(
            body["id_token"],
            options={"verify_signature": False},
        )
        assert ident["email"] == "local@mcp.dev"
        assert ident["name"] == "Local MCP User"
        assert ident["aud"] == registered_client["client_id"]

    def test_with_client_secret(self, oauth_client: TestClient,
                                 registered_client: dict):
        """Token exchange works when client_secret is provided."""
        # First get a code
        auth_resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
            },
            follow_redirects=False,
        ))
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
                "client_secret": registered_client["client_secret"],
            },
        )
        assert resp.status_code == 200

    def test_wrong_client_secret(self, oauth_client: TestClient,
                                  registered_client: dict,
                                  authorization_code: str):
        """A wrong client_secret returns 401."""
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
                "client_secret": "wrong-secret",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"] == "invalid_client"

    def test_invalid_client_id(self, oauth_client: TestClient,
                                authorization_code: str):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": "nonexistent",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_client"

    def test_invalid_code(self, oauth_client: TestClient,
                           registered_client: dict):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "invalid-code",
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    def test_code_reuse_fails(self, oauth_client: TestClient,
                               registered_client: dict,
                               authorization_code: str):
        """An authorization code can only be redeemed once."""
        # First use — should succeed
        r1 = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert r1.status_code == 200

        # Second use — must fail
        r2 = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert r2.status_code == 400
        assert r2.json()["error"] == "invalid_grant"

    def test_expired_code(self, oauth_client: TestClient,
                           registered_client: dict, monkeypatch):
        """An authorization code older than 300 s is rejected."""
        # Get a code first
        auth_resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
            },
            follow_redirects=False,
        ))
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        # Travel forward in time past the 300 s expiry
        # Capture the real time.time to avoid infinite recursion
        original_time = time.time
        monkeypatch.setattr("time.time", lambda: original_time() + 301)

        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error_description"] == "code expired"

    def test_unsupported_grant_type(self, oauth_client: TestClient,
                                     registered_client: dict,
                                     authorization_code: str):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "unsupported_grant_type"

    def test_code_verifier_is_accepted(self, oauth_client: TestClient,
                                        registered_client: dict):
        """The token endpoint accepts a code_verifier parameter.

        Note: the current implementation stores code_challenge but does
        NOT validate it against code_verifier. This test merely asserts
        the parameter doesn't cause an error.
        """
        # Authorize with a plain challenge
        auth_resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered_client["client_id"],
                "redirect_uri": "https://client.example/cb",
                "code_challenge": "challenge123",
                "code_challenge_method": "plain",
            },
            follow_redirects=False,
        ))
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        # Exchange with a verifier — succeeds (validation is a TODO)
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
                "code_verifier": "challenge123",
            },
        )
        assert resp.status_code == 200


# ===================================================================
#  JWKS endpoint
# ===================================================================

class TestJwks:
    def test_jwks_returns_rsa_key(self, oauth_client: TestClient):
        resp = oauth_client.get("/oauth/jwks.json")
        assert resp.status_code == 200
        body = resp.json()
        assert "keys" in body
        assert len(body["keys"]) >= 1
        key = body["keys"][0]
        assert key["kty"] == "RSA"
        assert key["alg"] == "RS256"
        assert key["kid"] == "test-key-id"
        assert "n" in key  # modulus
        assert "e" in key  # exponent


# ===================================================================
#  PKCE (S256) full flow
# ===================================================================

class TestPKCE:
    def test_s256_flow(self, oauth_client: TestClient):
        """Demonstrate a complete S256 PKCE flow."""
        # 1. Register a client
        reg = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://pkce-client.example/cb"],
        }).json()

        # 2. Generate code_verifier and challenge
        code_verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        # 3. Authorize with the challenge
        auth_resp = complete_authorization(oauth_client, oauth_client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": reg["client_id"],
                "redirect_uri": "https://pkce-client.example/cb",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "state": "pkce-state",
            },
            follow_redirects=False,
        ))
        assert auth_resp.status_code in (302, 307)
        code = auth_resp.headers["location"].split("code=")[1].split("&")[0]

        # 4. Exchange with the verifier
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://pkce-client.example/cb",
                "client_id": reg["client_id"],
                "code_verifier": code_verifier,
            },
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()


# ===================================================================
#  Token introspection / JWT content
# ===================================================================

class TestJWTContent:
    def test_access_token_uses_rs256(self, oauth_client: TestClient,
                                      registered_client: dict,
                                      authorization_code: str):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        token = resp.json()["access_token"]

        # Decode header
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert header["kid"] == "test-key-id"

    def test_token_ttl_respected(self, oauth_client: TestClient,
                                   registered_client: dict,
                                   authorization_code: str, monkeypatch):
        # Temporarily set a different TTL
        import lightweight_oauth as oauth_mod
        monkeypatch.setattr(oauth_mod, "TOKEN_TTL_SECONDS", 7200)

        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        assert resp.json()["expires_in"] == 7200

    def test_id_token_contains_user_info(self, oauth_client: TestClient,
                                          registered_client: dict,
                                          authorization_code: str):
        resp = oauth_client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "https://client.example/cb",
                "client_id": registered_client["client_id"],
            },
        )
        ident = jwt.decode(
            resp.json()["id_token"],
            options={"verify_signature": False},
        )
        assert ident["sub"] == "local-user"
        assert ident["email"] == "local@mcp.dev"
        assert ident["name"] == "Local MCP User"


# ===================================================================
#  Edge cases
# ===================================================================

class TestEdgeCases:
    def test_missing_grant_type(self, oauth_client: TestClient):
        resp = oauth_client.post("/oauth/token", data={})
        # FastAPI will reject the missing form field with 422
        assert resp.status_code == 422

    def test_register_without_redirect_uris(self, oauth_client: TestClient,
                                             temp_data_dir):
        resp = oauth_client.post("/oauth/register", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert body["redirect_uris"] == []

    def test_nonexistent_jwks(self, oauth_client: TestClient):
        resp = oauth_client.get("/oauth/jwks.json")
        assert resp.status_code == 200

    def test_multiple_codes_same_client(self, oauth_client: TestClient,
                                         registered_client: dict):
        """A client can obtain multiple authorization codes."""
        codes = []
        for _ in range(3):
            resp = complete_authorization(oauth_client, oauth_client.get(
                "/oauth/authorize",
                params={
                    "response_type": "code",
                    "client_id": registered_client["client_id"],
                    "redirect_uri": "https://client.example/cb",
                },
                follow_redirects=False,
            ))
            codes.append(resp.headers["location"].split("code=")[1].split("&")[0])

        assert len(set(codes)) == 3  # all different

        # Each code can be exchanged once
        for code in codes:
            r = oauth_client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": "https://client.example/cb",
                    "client_id": registered_client["client_id"],
                },
            )
            assert r.status_code == 200


def test_oauth_register_is_published_to_realtime_activity(oauth_client, temp_data_dir):
    import lightweight_oauth as oauth_mod
    from realtime_calls import RealtimeCallStore

    store = RealtimeCallStore()
    previous = oauth_mod.set_activity_observer(store)
    try:
        response = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://client.example/callback"],
            "client_name": "Realtime test",
        })
    finally:
        oauth_mod.set_activity_observer(previous)

    assert response.status_code == 200
    call = store.snapshot()["calls"][0]
    assert call["kind"] == "oauth"
    assert call["tool"] == "oauth.register"
    assert call["status"] == "success"
    assert call["http_status"] == 200
    assert call["conversation_id"] is None
    assert "client_secret" not in repr(call)
    assert response.json()["client_secret"] not in repr(call)


def test_oauth_authorize_and_failed_token_are_correlated_without_secret_leak(oauth_client, temp_data_dir):
    import lightweight_oauth as oauth_mod
    from realtime_calls import RealtimeCallStore

    store = RealtimeCallStore()
    previous = oauth_mod.set_activity_observer(store)
    try:
        registered = oauth_client.post("/oauth/register", json={
            "redirect_uris": ["https://client.example/callback"],
            "client_name": "Realtime auth client",
        }).json()
        authorize = oauth_client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": "https://client.example/callback",
        })
        failed_token = oauth_client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": "invalid-code",
            "redirect_uri": "https://client.example/callback",
            "client_id": registered["client_id"],
            "client_secret": registered["client_secret"],
        })
    finally:
        oauth_mod.set_activity_observer(previous)

    assert authorize.status_code == 200
    assert failed_token.status_code == 400
    calls = store.snapshot()["calls"]
    authorize_call = next(item for item in calls if item["tool"] == "oauth.authorize")
    token_call = next(item for item in calls if item["tool"] == "oauth.token")
    assert authorize_call["client_id"] == registered["client_id"]
    assert authorize_call["status"] == "success"
    assert token_call["status"] == "failed"
    assert token_call["http_status"] == 400
    assert registered["client_secret"] not in repr(calls)
    assert "invalid-code" not in repr(calls)


def test_oauth_metadata_monitor_matches_only_known_well_known_paths():
    from http_activity_monitor import _activity_name

    known = {
        "/.well-known/oauth-authorization-server/oauth",
        "/.well-known/openid-configuration/oauth",
        "/oauth/.well-known/oauth-authorization-server",
        "/oauth/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    }
    assert all(_activity_name("GET", path) == ("oauth.metadata", "oauth") for path in known)
    assert _activity_name("GET", "/assets/well-known-logo.svg") is None
    assert _activity_name("GET", "/other/.well-known/service") is None


def test_public_file_activity_does_not_persist_share_token():
    import asyncio

    from http_activity_monitor import OAuthActivityMiddleware, set_activity_observer
    from realtime_calls import RealtimeCallStore

    store = RealtimeCallStore()
    secret_share_id = "share-super-secret-token"

    async def application(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    previous = set_activity_observer(store)
    try:
        asyncio.run(OAuthActivityMiddleware(application)(
            {
                "type": "http",
                "method": "GET",
                "path": f"/public-files/{secret_share_id}",
                "query_string": b"",
            },
            receive,
            send,
        ))
    finally:
        set_activity_observer(previous)

    call = store.snapshot()["calls"][0]
    assert call["tool"] == "public_file.download"
    assert secret_share_id not in call["purpose"]
    assert secret_share_id not in repr(call)
