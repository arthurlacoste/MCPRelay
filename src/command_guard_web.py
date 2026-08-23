from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from command_guard import CustomGuardProvider, GuardRequest, GuardService
from command_guard_config import CustomGuardRule, CustomGuardStore, GuardConfigError

MAX_COMMAND_GUARD_BODY_BYTES = 65536
ACTION_HEADER = "X-Gate-Action"
ACTION_VALUE = "command-guard"


class CommandGuardBodyLimitMiddleware:
    def __init__(self, application, *, max_bytes: int = MAX_COMMAND_GUARD_BODY_BYTES) -> None:
        self.application = application
        self.max_bytes = max(1, int(max_bytes))

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PUT", "DELETE"}
            or not scope["path"].startswith("/rt/api/command-guards")
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


def register_command_guard_routes(
    app,
    service: GuardService,
    store: CustomGuardStore,
    authenticated: Callable[[Request], bool],
    event_logger: Callable[[str, dict[str, Any]], None] | None = None,
) -> None:
    app.add_middleware(CommandGuardBodyLimitMiddleware)
    mutation_lock = threading.RLock()

    def unauthorized() -> JSONResponse:
        return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

    def mutation_error(request: Request) -> JSONResponse | None:
        if not authenticated(request):
            return unauthorized()
        media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            return JSONResponse({"error": "json_required"}, status_code=415)
        if request.headers.get(ACTION_HEADER) != ACTION_VALUE:
            return JSONResponse({"error": "action_header_required"}, status_code=403)
        return None

    async def read_json(request: Request) -> Mapping[str, Any] | JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse({"error": "invalid_json"}, status_code=400)
        if not isinstance(payload, Mapping):
            return JSONResponse({"error": "invalid_payload"}, status_code=400)
        return payload

    def snapshot_payload() -> dict[str, Any]:
        custom = [rule.as_dict() for rule in service.custom_rules()]
        return {
            "provider": service.provider_name,
            "fallback": service.fallback_name,
            "disabled": service.provider_name == "disabled",
            "builtin": service.builtin_rules(),
            "custom": custom,
        }

    def persist(rules: list[CustomGuardRule]) -> None:
        snapshot = store.save(rules)
        service.replace_custom_rules(snapshot)

    def audit(action: str, rule_id: str, change: str) -> None:
        if event_logger:
            event_logger(action, {"id": rule_id, "change": change})

    @app.get("/rt/api/command-guards")
    def list_command_guards(request: Request):
        if not authenticated(request):
            return unauthorized()
        return snapshot_payload()

    @app.post("/rt/api/command-guards/custom")
    async def create_custom_guard(request: Request):
        error = mutation_error(request)
        if error:
            return error
        payload = await read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            rule = CustomGuardRule.from_mapping(payload)
            with mutation_lock:
                rules = list(service.custom_rules())
                if any(item.id == rule.id for item in rules):
                    return JSONResponse({"error": "duplicate_id"}, status_code=409)
                rules.append(rule)
                persist(rules)
        except GuardConfigError as exc:
            return JSONResponse({"error": "invalid_rule", "detail": str(exc)}, status_code=422)
        audit("command_guard_rule_created", rule.id, "create")
        return JSONResponse(rule.as_dict(), status_code=201)

    @app.put("/rt/api/command-guards/custom/{rule_id}")
    async def update_custom_guard(rule_id: str, request: Request):
        error = mutation_error(request)
        if error:
            return error
        payload = await read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        try:
            rule = CustomGuardRule.from_mapping(payload)
            if rule.id != rule_id:
                return JSONResponse({"error": "id_mismatch"}, status_code=409)
            with mutation_lock:
                rules = list(service.custom_rules())
                index = next((index for index, item in enumerate(rules) if item.id == rule_id), None)
                if index is None:
                    return JSONResponse({"error": "not_found"}, status_code=404)
                rules[index] = rule
                persist(rules)
        except GuardConfigError as exc:
            return JSONResponse({"error": "invalid_rule", "detail": str(exc)}, status_code=422)
        audit("command_guard_rule_updated", rule.id, "update")
        return rule.as_dict()

    @app.delete("/rt/api/command-guards/custom/{rule_id}")
    async def delete_custom_guard(rule_id: str, request: Request):
        error = mutation_error(request)
        if error:
            return error
        payload = await read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        if payload:
            return JSONResponse({"error": "invalid_payload"}, status_code=400)
        with mutation_lock:
            rules = list(service.custom_rules())
            filtered = [item for item in rules if item.id != rule_id]
            if len(filtered) == len(rules):
                return JSONResponse({"error": "not_found"}, status_code=404)
            persist(filtered)
        audit("command_guard_rule_deleted", rule_id, "delete")
        return JSONResponse({"ok": True, "id": rule_id})

    @app.post("/rt/api/command-guards/test")
    async def test_command_guard(request: Request):
        error = mutation_error(request)
        if error:
            return error
        payload = await read_json(request)
        if isinstance(payload, JSONResponse):
            return payload
        unknown = set(payload) - {"command", "cwd", "candidate"}
        if unknown:
            return JSONResponse({"error": "invalid_payload"}, status_code=400)
        command = payload.get("command")
        cwd = payload.get("cwd")
        if not isinstance(command, str) or not command.strip() or len(command) > 20000:
            return JSONResponse({"error": "invalid_command"}, status_code=422)
        if cwd is not None and (not isinstance(cwd, str) or len(cwd) > 1000):
            return JSONResponse({"error": "invalid_cwd"}, status_code=422)
        request_to_test = GuardRequest("command_guard_test", {}, command, cwd or None)
        candidate = payload.get("candidate")
        if candidate is not None:
            try:
                candidate_rule = CustomGuardRule.from_mapping(candidate)
            except GuardConfigError as exc:
                return JSONResponse({"error": "invalid_rule", "detail": str(exc)}, status_code=422)
            if service.provider_name != "disabled":
                effective_rules = [rule for rule in service.custom_rules() if rule.id != candidate_rule.id]
                effective_rules.append(candidate_rule)
                candidate_result = CustomGuardProvider(effective_rules).inspect(request_to_test)
                if candidate_result.decision == "deny":
                    return candidate_result.as_dict()
                return service.inspect_without_custom(request_to_test).as_dict()
        result = service.inspect(request_to_test)
        return result.as_dict()
