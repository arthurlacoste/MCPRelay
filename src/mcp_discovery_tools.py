from __future__ import annotations

from typing import Any

from tool_registry import configurable_tool


READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


def register_mcp_discovery_tools(mcp, proxy_manager) -> None:
    @configurable_tool(
        mcp,
        title="Search MCP tools",
        description="Search tools from configured MCP subservers without exposing their schemas in the initial tool list.",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def mcp_tools_search(
        query: str | None = None,
        server_name: str | None = None,
        limit: int = 8,
        offset: int = 0,
    ) -> dict:
        return proxy_manager.search_tools(query, server_name=server_name, limit=limit, offset=offset)

    @configurable_tool(
        mcp,
        title="Read MCP tool schema",
        description="Read the schema and metadata for one discovered MCP subserver tool.",
        annotations=READ_ONLY_ANNOTATIONS,
    )
    async def mcp_tool_read(server_name: str, tool_name: str) -> dict:
        return proxy_manager.read_tool(server_name, tool_name)

    @configurable_tool(
        mcp,
        title="Call MCP tool",
        description="Invoke one discovered MCP subserver tool with its arguments. Use mcp_tool_read first when the schema is not known.",
    )
    async def mcp_tool_call(
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict:
        return await proxy_manager.call_tool(server_name, tool_name, arguments)
