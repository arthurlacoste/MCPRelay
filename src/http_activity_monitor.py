from __future__ import annotations

from urllib.parse import parse_qs



OAUTH_METADATA_PATHS = frozenset({
    "/.well-known/oauth-authorization-server/oauth",
    "/.well-known/openid-configuration/oauth",
    "/oauth/.well-known/oauth-authorization-server",
    "/oauth/.well-known/openid-configuration",
    "/.well-known/oauth-authorization-server",
    "/.well-known/openid-configuration",
})

_activity_observer = None


def set_activity_observer(observer):
    global _activity_observer
    previous = _activity_observer
    _activity_observer = observer
    return previous


def _activity_name(method: str, path: str) -> tuple[str, str] | None:
    if path == "/oauth/register" and method == "POST":
        return "oauth.register", "oauth"
    if path == "/oauth/authorize" and method in {"GET", "POST"}:
        return "oauth.authorize", "oauth"
    if path == "/oauth/token" and method == "POST":
        return "oauth.token", "oauth"
    if path == "/oauth/jwks.json" and method == "GET":
        return "oauth.jwks", "oauth"
    if path in OAUTH_METADATA_PATHS and method == "GET":
        return "oauth.metadata", "oauth"
    if path.startswith("/public-files/") and method == "GET":
        return "public_file.download", "http"
    return None


class OAuthActivityMiddleware:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        observer = _activity_observer
        if scope.get("type") != "http" or observer is None:
            return await self.application(scope, receive, send)
        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")
        activity = _activity_name(method, path)
        if activity is None:
            return await self.application(scope, receive, send)

        tool, kind = activity
        client_id = None
        if path == "/oauth/authorize" and method == "GET":
            query = parse_qs(scope.get("query_string", b"").decode("utf-8", errors="ignore"))
            values = query.get("client_id")
            client_id = values[0] if values else None
        purpose = "Download public file" if tool == "public_file.download" else f"{method} {path}"
        activity_id = observer.start_activity(
            tool=tool,
            kind=kind,
            purpose=purpose,
            client_id=client_id,
        )
        status_code = 500

        async def send_with_status(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 500)
            await send(message)

        try:
            await self.application(scope, receive, send_with_status)
        except Exception:
            observer.finish_activity(activity_id, status="failed", http_status=500)
            raise
        observer.finish_activity(
            activity_id,
            status="success" if status_code < 400 else "failed",
            http_status=status_code,
        )
