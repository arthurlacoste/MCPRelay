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


def test_repeated_failed_reloads_keep_last_healthy_provider(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        retry_initial_seconds=0,
    )

    async def scenario():
        await manager.start(gateway)
        original_provider = manager.registry.states["demo"].provider
        _write_config(config, {"demo": {"command": "/missing/server"}})
        await manager.refresh()
        await manager.refresh()
        state = manager.registry.states["demo"]
        result = await gateway.call_tool("demo_echo", {})
        providers = list(gateway.providers)
        await manager.close()
        return original_provider, state, result, providers

    original_provider, state, result, providers = asyncio.run(scenario())
    assert state.status == "degraded"
    assert state.provider is original_provider
    assert state.client is not None
    assert original_provider in providers
    assert result.content[0].text == "ok"


def test_native_tool_registered_after_start_blocks_proxy_collision(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)

        @gateway.tool(name="demo_echo")
        def native_echo() -> str:
            return "native"

        _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "proxy"]}})
        diff = await manager.refresh()
        result = await gateway.call_tool("demo_echo", {})
        status = manager.server_status("demo")
        await manager.close()
        return diff, result, status

    diff, result, status = asyncio.run(scenario())
    assert not diff.changed
    assert result.content[0].text == "native"
    assert status["status"] == "offline"
    assert status["last_error"] == "ValueError"


def test_failed_reload_is_not_reported_as_catalog_change(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        _write_config(config, {"broken": {"command": "/missing/server"}})
        diff = await manager.refresh()
        await manager.close()
        return diff

    diff = asyncio.run(scenario())
    assert not diff.changed
    assert diff.added_servers == set()
    assert diff.changed_servers == set()


def test_negative_refresh_interval_is_clamped_to_zero(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=-5)

    assert manager.registry.refresh_interval_seconds == 0
