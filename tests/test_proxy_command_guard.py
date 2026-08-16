import asyncio
import json
import sys

import pytest
from fastmcp import Client, FastMCP

from command_guard import GuardService
from mcp_proxy import MCPProxyManager


def test_declared_proxy_shell_tool_is_denied_before_forwarding(tmp_path):
    marker = tmp_path / "forwarded"
    server = tmp_path / "server.py"
    server.write_text(
        "from pathlib import Path\n"
        "from fastmcp import FastMCP\n"
        "mcp=FastMCP('fixture')\n"
        f"@mcp.tool\ndef execute(command: str, cwd: str | None=None): Path({str(marker)!r}).write_text(command); return 'ran'\n"
        "mcp.run(transport='stdio')\n"
    )
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"shell": {
        "command": sys.executable,
        "args": [str(server)],
        "commandGuards": {"execute": {"commandArgument": "command", "cwdArgument": "cwd"}},
    }}}))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, command_guard=GuardService(), tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            with pytest.raises(Exception, match="denied"):
                await gateway.call_tool("shell_execute", {"command": "git reset --hard", "cwd": str(tmp_path)})
        finally:
            await manager.close()

    asyncio.run(scenario())
    assert not marker.exists()

def test_known_proxy_shell_tools_are_guarded_without_explicit_mapping(tmp_path):
    from command_guard import GuardService
    from mcp_proxy import ProxyCommandGuardMiddleware
    middleware = ProxyCommandGuardMiddleware(
        "remote",
        {"filesystem_execute_tool": {"commandArgument": "command", "cwdArgument": "cwd"}},
        GuardService(),
    )
    assert "filesystem_execute_tool" in middleware.mappings


def test_discover_route_runs_command_guard_and_proxy_logging(tmp_path):
    marker = tmp_path / "forwarded"
    server = tmp_path / "server.py"
    server.write_text(
        "from pathlib import Path\n"
        "from fastmcp import FastMCP\n"
        "mcp=FastMCP('fixture')\n"
        f"@mcp.tool\ndef execute(command: str, cwd: str | None=None): Path({str(marker)!r}).write_text(command); return command\n"
        "mcp.run(transport='stdio')\n"
    )
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"shell": {
        "command": sys.executable,
        "args": [str(server)],
        "commandGuards": {"execute": {"commandArgument": "command", "cwdArgument": "cwd"}},
    }}}))
    events = []
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        command_guard=GuardService(provider="builtin"),
        event_logger=lambda action, payload: events.append((action, payload)),
        tool_exposure_mode="discover",
    )
    dangerous = "git " + "reset --hard"
    safe = "git status --short"

    async def scenario():
        await manager.start(gateway)
        try:
            exposed = {tool.name for tool in await gateway.list_tools()}
            with pytest.raises(Exception, match="denied"):
                await manager.call_tool("shell", "execute", {"command": dangerous, "cwd": str(tmp_path)})
            denied_marker_exists = marker.exists()
            allowed = await manager.call_tool("shell", "execute", {"command": safe, "cwd": str(tmp_path)})
            return exposed, denied_marker_exists, allowed
        finally:
            await manager.close()

    exposed, denied_marker_exists, allowed = asyncio.run(scenario())

    assert "shell_execute" not in exposed
    assert denied_marker_exists is False
    assert marker.read_text() == safe
    assert allowed["content"][0]["text"] == safe
    proxy_events = [payload for action, payload in events if action == "mcp_proxy_call"]
    assert [event["status"] for event in proxy_events] == ["success"]
    assert all(event["server"] == "shell" and event["tool"] == "execute" for event in proxy_events)
    assert dangerous not in repr(proxy_events)
    assert safe not in repr(proxy_events)
