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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, command_guard=GuardService())

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
