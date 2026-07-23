import asyncio
import json
import sys

from fastmcp import FastMCP


def _server_script(tmp_path):
    path = tmp_path / "dynamic_server.py"
    path.write_text(
        "import sys\n"
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('dynamic')\n"
        "name, value = sys.argv[1], sys.argv[2]\n"
        "def handler() -> str: return value\n"
        "mcp.tool(name=name)(handler)\n"
        "mcp.run(transport='stdio')\n"
    )
    return path


def _write_config(path, servers):
    path.write_text(json.dumps({"mcpServers": servers}))


def test_refresh_adds_changes_and_removes_server(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "first", "one"]}})
        added = await manager.refresh()
        first = await gateway.call_tool("demo_first", {})
        _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "second", "two"]}})
        changed = await manager.refresh()
        names = {tool.name for tool in await gateway.list_tools()}
        second = await gateway.call_tool("demo_second", {})
        _write_config(config, {})
        removed = await manager.refresh()
        final_names = {tool.name for tool in await gateway.list_tools()}
        await manager.close()
        return added, changed, removed, first, second, names, final_names

    added, changed, removed, first, second, names, final_names = asyncio.run(scenario())
    assert added.added_servers == {"demo"}
    assert changed.changed_servers == {"demo"}
    assert removed.removed_servers == {"demo"}
    assert first.content[0].text == "one"
    assert second.content[0].text == "two"
    assert names == {"demo_second"}
    assert final_names == set()


def test_failed_reload_preserves_last_healthy_catalog(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        _write_config(config, {"demo": {"command": "/missing/server"}})
        await manager.refresh()
        result = await gateway.call_tool("demo_echo", {})
        status = manager.server_status("demo")
        await manager.close()
        return result, status

    result, status = asyncio.run(scenario())
    assert result.content[0].text == "ok"
    assert status["status"] == "degraded"
    assert status["retry_count"] == 1
    assert status["next_retry_at"] is not None


def test_concurrent_refresh_is_serialized_and_unchanged_is_noop(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        diffs = await asyncio.gather(manager.refresh(), manager.refresh())
        await manager.close()
        return diffs

    assert all(not diff.changed for diff in asyncio.run(scenario()))


def test_registry_management_methods_report_current_state(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        listed = manager.list_servers()
        status = manager.server_status("demo")
        reloaded = await manager.reload_server("demo")
        await manager.remove_server("demo")
        missing = manager.server_status("demo")
        await manager.close()
        return listed, status, reloaded.as_dict(), missing

    listed, status, reloaded, missing = asyncio.run(scenario())
    assert [item["name"] for item in listed] == ["demo"]
    assert status["tool_count"] == 1
    assert "resource_count" not in status
    assert "prompt_count" not in status
    assert reloaded["status"] == "healthy"
    assert missing is None
