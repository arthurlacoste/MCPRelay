from __future__ import annotations

from typing import Any

from gate_tool_catalog import SERVER_NAME
from tool_registry import configurable_tool


READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def register_mcp_discovery_tools(mcp, proxy_manager) -> None:
    catalog = getattr(mcp, "_gate_tool_catalog", None)

    @configurable_tool(
        mcp,
        title="Search MCP tools",
        description="Search tools from Gate and configured MCP subservers without exposing their schemas in the initial tool list.",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def mcp_tools_search(
        query: str | None = None,
        server_name: str | None = None,
        limit: int = 8,
        offset: int = 0,
    ) -> dict:
        if catalog is not None and server_name == SERVER_NAME:
            return catalog.search(query, limit=limit, offset=offset)
        if server_name is not None:
            return proxy_manager.search_tools(query, server_name=server_name, limit=limit, offset=offset)
        if catalog is None:
            return proxy_manager.search_tools(query, limit=limit, offset=offset)
        start = max(0, offset)
        size = min(max(1, limit), 100)
        local = catalog.search(query, limit=size, offset=start)
        remaining = size - len(local["matches"])
        remote_offset = max(0, start - local["total"])
        remote = proxy_manager.search_tools(
            query,
            limit=max(1, remaining),
            offset=remote_offset if start >= local["total"] else 0,
        )
        matches = local["matches"] + (remote["matches"][:remaining] if remaining else [])
        total = local["total"] + remote["total"]
        return {"matches": matches, "total": total, "has_more": start + len(matches) < total}

    @configurable_tool(
        mcp,
        title="Read MCP tool schema",
        description="Read the schema and metadata for one discovered Gate or MCP subserver tool.",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def mcp_tool_read(server_name: str, tool_name: str) -> dict:
        if catalog is not None and server_name == SERVER_NAME:
            return catalog.read(tool_name)
        return proxy_manager.read_tool(server_name, tool_name)

    @configurable_tool(
        mcp,
        title="Call MCP tool",
        description="Invoke one discovered Gate or MCP subserver tool with its arguments. Use mcp_tool_read first when the schema is not known.",
    )
    async def mcp_tool_call(
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict:
        if catalog is not None and server_name == SERVER_NAME:
            return await catalog.call(tool_name, arguments)
        return await proxy_manager.call_tool(server_name, tool_name, arguments)
