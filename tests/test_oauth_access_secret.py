import re
import time
from urllib.parse import parse_qs, urlparse

from argon2 import PasswordHasher

import lightweight_oauth as oauth_mod
from oauth_access_gate import OAuthAccessGate, client_address, trusted_proxy_networks


ACCESS_SECRET = "correct horse battery staple"


def start_authorization(client, registered_client, **overrides):
    params = {
        "response_type": "code",
        "client_id": registered_client["client_id"],
        "redirect_uri": "https://client.example/cb",
        "state": "signed-state",
        "scope": "openid profile",
        "code_challenge": "challenge",
        "code_challenge_method": "plain",
        "audience": "https://custom.example/mcp",
    }
    params.update(overrides)
    return client.get("/oauth/authorize", params=params, follow_redirects=False)


def request_id(response):
    match = re.search(r'name="request" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def authorize(client, request, secret=ACCESS_SECRET):
    return client.post(
        "/oauth/authorize",
        data={"request": request, "secret": secret},
        follow_redirects=False,
    )


def test_authorization_page_shows_request_details(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    assert "Test Client" in response.text
    assert "https://client.example/cb" in response.text
    assert "openid profile" in response.text
    assert "https://custom.example/mcp" in response.text
    assert 'value="deny"' in response.text


def test_authorization_page_uses_centered_responsive_theme(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    assert "vision.webp" not in response.text
    assert 'class="primary"' in response.text
    assert 'class="secondary"' in response.text
    assert 'class="request-details"' in response.text
    assert "prefers-color-scheme:dark" in response.text
    assert 'content="width=device-width,initial-scale=1"' in response.text
    assert "body{min-height:100vh" in response.text
    assert "font:16px/1.45" in response.text
    assert "font-size:16px;outline:none" in response.text
    assert response.text.index('class="secondary"') < response.text.index('class="request-details"')


def test_oauth_vision_asset_is_not_exposed(oauth_client):
    response = oauth_client.get("/oauth/assets/vision.webp")
    assert response.status_code == 404


def test_authorization_can_be_denied(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    result = oauth_client.post(
        "/oauth/authorize",
        data={"request": request_id(response), "decision": "deny"},
        follow_redirects=False,
    )
    assert result.status_code in (302, 307)
    query = parse_qs(urlparse(result.headers["location"]).query)
    assert query == {"error": ["access_denied"], "state": ["signed-state"]}
    assert oauth_mod.load_codes() == {}


def test_authorization_body_is_bounded_before_form_parsing(oauth_client):
    response = oauth_client.post(
        "/oauth/authorize",
        content=b"secret=" + b"x" * 5000,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413
    response = oauth_client.post(
        "/oauth/authorize",
        files={"secret": (None, "x" * 5000)},
    )
    assert response.status_code == 413


def test_authorization_requires_secret(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    assert response.status_code == 200
    assert "code=" not in response.text
    assert ACCESS_SECRET not in response.text
    assert oauth_mod.load_codes() == {}


def test_correct_secret_preserves_server_side_request(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    result = authorize(oauth_client, request_id(response))
    assert result.status_code in (302, 307)
    query = parse_qs(urlparse(result.headers["location"]).query)
    assert query["state"] == ["signed-state"]
    item = oauth_mod.load_codes()[query["code"][0]]
    assert item["client_id"] == registered_client["client_id"]
    assert item["code_challenge"] == "challenge"
    assert item["audience"] == "https://custom.example/mcp"


def test_wrong_secret_creates_no_code_and_does_not_leak(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    result = authorize(oauth_client, request_id(response), "very-wrong-secret")
    assert result.status_code == 401
    assert "very-wrong-secret" not in result.text
    assert oauth_mod.load_codes() == {}


def test_pending_request_is_single_use_and_expires(oauth_client, registered_client, monkeypatch):
    response = start_authorization(oauth_client, registered_client)
    pending_id = request_id(response)
    assert authorize(oauth_client, pending_id).status_code in (302, 307)
    assert authorize(oauth_client, pending_id).status_code == 400

    response = start_authorization(oauth_client, registered_client)
    pending_id = request_id(response)
    now = time.time()
    monkeypatch.setattr(oauth_mod.time, "time", lambda: now + 301)
    assert authorize(oauth_client, pending_id).status_code == 400


def test_rate_limit_is_per_ip(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    pending_id = request_id(response)
    for _ in range(oauth_mod.LOGIN_MAX_ATTEMPTS):
        assert authorize(oauth_client, pending_id, "wrong").status_code == 401
    limited = authorize(oauth_client, pending_id, "wrong")
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_invalid_hash_fails_closed(oauth_client, registered_client, monkeypatch):
    monkeypatch.setattr(oauth_mod, "ACCESS_SECRET_HASH", "invalid")
    response = start_authorization(oauth_client, registered_client)
    assert authorize(oauth_client, request_id(response)).status_code == 503


def test_missing_hash_fails_closed(oauth_client, registered_client, monkeypatch):
    monkeypatch.setattr(oauth_mod, "ACCESS_SECRET_HASH", "")
    response = start_authorization(oauth_client, registered_client)
    assert authorize(oauth_client, request_id(response)).status_code == 503


def test_forwarded_address_requires_explicit_trusted_proxy():
    local = trusted_proxy_networks("127.0.0.0/8")
    assert client_address("203.0.113.10", "198.51.100.2", local) == "203.0.113.10"
    assert client_address("127.0.0.1", "198.51.100.2, 127.0.0.2", local) == "198.51.100.2"
    assert client_address("127.0.0.1", "spoofed", local) == "127.0.0.1"
    assert client_address("127.0.0.1", "198.51.100.99", ()) == "127.0.0.1"


def test_forwarded_address_ignores_injected_leftmost_value():
    proxies = trusted_proxy_networks("127.0.0.0/8,10.0.0.0/8")
    clean = client_address("127.0.0.1", "198.51.100.2, 10.0.0.3", proxies)
    injected = client_address("127.0.0.1", "203.0.113.77, 198.51.100.2, 10.0.0.3", proxies)
    assert clean == injected == "198.51.100.2"


def test_capacity_recovers_after_windows_expire(monkeypatch):
    gate = OAuthAccessGate()
    hasher = PasswordHasher().hash(ACCESS_SECRET)
    now = 120.0
    monkeypatch.setattr("oauth_access_gate.time.time", lambda: now)
    monkeypatch.setattr("oauth_access_gate.MAX_RATE_LIMIT_ADDRESSES", 2)
    assert gate.authenticate("one", 5, hasher, "wrong") == "invalid"
    assert gate.authenticate("two", 5, hasher, "wrong") == "invalid"
    assert gate.authenticate("three", 5, hasher, "wrong") == "limited"
    now = 180.0
    assert gate.authenticate("three", 5, hasher, "wrong") == "invalid"


def test_pending_capacity_is_limited_per_source(monkeypatch):
    gate = OAuthAccessGate()
    monkeypatch.setattr("oauth_access_gate.MAX_PENDING_PER_SOURCE", 1)
    assert gate.create({}, "source")
    assert gate.create({}, "source") is None
    assert gate.create({}, "other")


def test_rate_limit_uses_fixed_window(monkeypatch):
    gate = OAuthAccessGate()
    hasher = PasswordHasher().hash(ACCESS_SECRET)
    now = 120.0
    monkeypatch.setattr("oauth_access_gate.time.time", lambda: now)
    assert gate.authenticate("client", 1, hasher, "wrong") == "invalid"
    now = 179.0
    assert gate.authenticate("client", 1, hasher, "wrong") == "limited"
    now = 180.0
    assert gate.authenticate("client", 1, hasher, "wrong") == "invalid"


def test_success_resets_failures(oauth_client, registered_client):
    response = start_authorization(oauth_client, registered_client)
    pending_id = request_id(response)
    assert authorize(oauth_client, pending_id, "wrong").status_code == 401
    assert authorize(oauth_client, pending_id).status_code in (302, 307)
    assert oauth_mod.access_gate.failures == {}


def test_non_argon2id_hash_fails_closed(oauth_client, registered_client, monkeypatch):
    argon2i_hash = PasswordHasher(type=__import__("argon2").Type.I).hash(ACCESS_SECRET)
    monkeypatch.setattr(oauth_mod, "ACCESS_SECRET_HASH", argon2i_hash)
    response = start_authorization(oauth_client, registered_client)
    assert authorize(oauth_client, request_id(response)).status_code == 503


def test_fixture_uses_argon2id_hash():
    assert oauth_mod.ACCESS_SECRET_HASH.startswith("$argon2id$")
    assert PasswordHasher().verify(oauth_mod.ACCESS_SECRET_HASH, ACCESS_SECRET)
