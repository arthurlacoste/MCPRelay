"""Host-relative RFC 9728 metadata for Gate's HTTP transport."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource/mcp"


def _host_from_scope(scope: Scope) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == b"host":
            host = value.decode("latin-1").strip().lower().rstrip(".")
            return host or None
    return None


def _base_url(host: str | None, fallback_base_url: str) -> str:
    if host:
        return f"https://{host}"
    return fallback_base_url.rstrip("/")


def _resource_metadata_url(base_url: str) -> str:
    return f"{base_url}{PROTECTED_RESOURCE_PATH}"


def _replace_resource_metadata(header: str, metadata_url: str) -> str:
    marker = 'resource_metadata="'
    start = header.find(marker)
    if start < 0:
        return header
    value_start = start + len(marker)
    value_end = header.find('"', value_start)
    if value_end < 0:
        return header
    return f"{header[:value_start]}{metadata_url}{header[value_end:]}"


class HostRelativeOAuthMetadataMiddleware:
    """Make FastMCP RFC 9728 responses follow the incoming Host header.

    FastMCP builds protected-resource metadata and its auth challenge once at
    application startup from ``RemoteAuthProvider.base_url``. Gate can change
    public tunnel hosts without restarting its configuration, so those static
    URLs become stale. This middleware replaces only those public discovery
    URLs per request and leaves token verification untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        fallback_base_url: str,
        fallback_issuer: str,
    ) -> None:
        self.app = app
        self.fallback_base_url = fallback_base_url.rstrip("/")
        self.fallback_issuer = fallback_issuer.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host = _host_from_scope(scope)
        base_url = _base_url(host, self.fallback_base_url)
        issuer = f"{base_url}/oauth" if host else self.fallback_issuer

        if scope.get("method") == "GET" and scope.get("path") == PROTECTED_RESOURCE_PATH:
            response = JSONResponse(
                {
                    "resource": f"{base_url}/mcp",
                    "authorization_servers": [issuer],
                    "scopes_supported": [],
                    "bearer_methods_supported": ["header"],
                }
            )
            await response(scope, receive, send)
            return

        async def send_with_host_relative_metadata(message: Message) -> None:
            if message["type"] == "http.response.start":
                metadata_url = _resource_metadata_url(base_url)
                rewritten_headers: list[tuple[bytes, bytes]] = []
                for key, value in message.get("headers", []):
                    if key.lower() == b"www-authenticate":
                        text = value.decode("latin-1")
                        value = _replace_resource_metadata(text, metadata_url).encode("latin-1")
                    rewritten_headers.append((key, value))
                message = {**message, "headers": rewritten_headers}
            await send(message)

        await self.app(scope, receive, send_with_host_relative_metadata)
