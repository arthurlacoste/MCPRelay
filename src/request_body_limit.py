from __future__ import annotations

from collections.abc import Collection

from fastapi.responses import JSONResponse


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        application,
        *,
        path: str | None = None,
        path_prefix: str | None = None,
        methods: Collection[str] = ("POST",),
        max_bytes: int,
    ) -> None:
        if (path is None) == (path_prefix is None):
            raise ValueError("exactly one of path or path_prefix is required")
        self.application = application
        self.path = path
        self.path_prefix = path_prefix
        self.methods = frozenset(method.upper() for method in methods)
        self.max_bytes = max(1, int(max_bytes))

    def _matches(self, scope) -> bool:
        if scope["type"] != "http" or scope["method"].upper() not in self.methods:
            return False
        request_path = scope["path"]
        if self.path is not None:
            return request_path == self.path
        return request_path.startswith(self.path_prefix or "")

    async def __call__(self, scope, receive, send):
        if not self._matches(scope):
            return await self.application(scope, receive, send)

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
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
