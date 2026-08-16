from __future__ import annotations

import asyncio
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext

from realtime_calls import RealtimeCallStore, auto_conversation_id, session_ref


CONVERSATION_STATE_KEY = "gate_conversation_id"


class GateActivityMiddleware(Middleware):
    def __init__(self, store: RealtimeCallStore, *, excluded_tools: set[str] | None = None) -> None:
        self.store = store
        self.excluded_tools = set(excluded_tools or {"run_command"})

    async def _activity_context(self, context: MiddlewareContext, arguments: dict[str, Any]) -> dict[str, str | None]:
        ctx = context.fastmcp_context
        if ctx is None:
            return {"conversation_id": None, "session_ref": None, "request_id": None, "client_id": None}

        explicit = arguments.get("conversation_id")
        conversation_id = explicit if isinstance(explicit, str) and explicit.strip() else None
        try:
            raw_session_id = ctx.session_id
        except RuntimeError:
            raw_session_id = None

        if raw_session_id is not None:
            if conversation_id:
                await ctx.set_state(CONVERSATION_STATE_KEY, conversation_id)
            else:
                conversation_id = await ctx.get_state(CONVERSATION_STATE_KEY)
                if not isinstance(conversation_id, str) or not conversation_id:
                    conversation_id = auto_conversation_id(raw_session_id)
                    await ctx.set_state(CONVERSATION_STATE_KEY, conversation_id)

        try:
            request_id = str(ctx.request_id)
        except RuntimeError:
            request_id = None
        try:
            client_id = str(ctx.client_id) if ctx.client_id is not None else None
        except (AttributeError, RuntimeError):
            client_id = None

        return {
            "conversation_id": conversation_id,
            "session_ref": session_ref(raw_session_id) if raw_session_id is not None else None,
            "request_id": request_id,
            "client_id": client_id,
        }

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = context.message.name
        arguments = context.message.arguments or {}
        if tool_name in self.excluded_tools:
            activity_context = await self._activity_context(context, arguments)
            if (
                tool_name == "run_command"
                and not arguments.get("conversation_id")
                and activity_context.get("conversation_id")
            ):
                arguments["conversation_id"] = activity_context["conversation_id"]
            return await call_next(context)

        display_tool = tool_name
        kind = "tool"
        if tool_name == "mcp_tool_call":
            server_name = arguments.get("server_name")
            downstream_tool = arguments.get("tool_name")
            if isinstance(server_name, str) and isinstance(downstream_tool, str):
                display_tool = f"{server_name}.{downstream_tool}"
                kind = "mcp"
        activity_context = await self._activity_context(context, arguments)
        activity_id = self.store.start_activity(
            tool=display_tool,
            kind=kind,
            purpose=f"Call {display_tool}",
            **activity_context,
        )
        try:
            result = await call_next(context)
        except asyncio.CancelledError:
            self.store.finish_activity(activity_id, status="cancelled")
            raise
        except Exception:
            self.store.finish_activity(activity_id, status="failed")
            raise

        result_conversation_id = None
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            candidate = structured.get("conversation_id")
            if isinstance(candidate, str) and candidate.strip():
                result_conversation_id = candidate
        if result_conversation_id:
            if context.fastmcp_context is not None and activity_context.get("session_ref"):
                await context.fastmcp_context.set_state(CONVERSATION_STATE_KEY, result_conversation_id)
            activity_context["conversation_id"] = result_conversation_id

        self.store.finish_activity(activity_id, status="success", **activity_context)
        return result

    async def _record_non_tool(self, context: MiddlewareContext, call_next, *, tool: str, kind: str):
        activity_context = await self._activity_context(context, {})
        activity_id = self.store.start_activity(
            tool=tool,
            kind=kind,
            purpose=f"Read {tool}" if kind == "resource" else f"Get {tool}",
            **activity_context,
        )
        try:
            result = await call_next(context)
        except asyncio.CancelledError:
            self.store.finish_activity(activity_id, status="cancelled")
            raise
        except Exception:
            self.store.finish_activity(activity_id, status="failed")
            raise
        self.store.finish_activity(activity_id, status="success")
        return result

    async def on_read_resource(self, context: MiddlewareContext, call_next):
        return await self._record_non_tool(
            context,
            call_next,
            tool=f"resource:{context.message.uri}",
            kind="resource",
        )

    async def on_get_prompt(self, context: MiddlewareContext, call_next):
        return await self._record_non_tool(
            context,
            call_next,
            tool=f"prompt:{context.message.name}",
            kind="prompt",
        )
