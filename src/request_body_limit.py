from __future__ import annotations

from fastapi.responses import JSONResponse


class RequestBodyLimitMiddleware:
    def __init__(self, application, *, path: str, max_bytes: int) -> None:
        self.application = application
        self.path = path
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != self.path
        ):
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
