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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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


def test_invalid_registry_preserves_last_healthy_catalog(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        config.write_text('{"mcpServers": ')
        diff = await manager.refresh()
        result = await gateway.call_tool("demo_echo", {})
        status = manager.server_status("demo")
        await manager.close()
        return diff, result, status

    diff, result, status = asyncio.run(scenario())
    assert not diff.changed
    assert result.content[0].text == "ok"
    assert status["status"] == "healthy"


def test_missing_registry_preserves_last_healthy_catalog(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        config.unlink()
        diff = await manager.refresh()
        result = await gateway.call_tool("demo_echo", {})
        status = manager.server_status("demo")
        await manager.close()
        return diff, result, status

    diff, result, status = asyncio.run(scenario())
    assert not diff.changed
    assert result.content[0].text == "ok"
    assert status["status"] == "healthy"


def test_reload_server_keeps_key_error_contract_when_registry_is_unavailable(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        config.write_text('{"mcpServers": ')
        try:
            await manager.reload_server("demo")
        finally:
            await manager.close()

    import pytest
    with pytest.raises(KeyError, match="registry unavailable"):
        asyncio.run(scenario())


def test_concurrent_refresh_is_serialized_and_unchanged_is_noop(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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
        tool_exposure_mode="full",
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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0, tool_exposure_mode="full")

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
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=-5, tool_exposure_mode="full")

    assert manager.registry.refresh_interval_seconds == 0


def test_discover_mode_keeps_proxy_tools_hidden_but_searchable_readable_and_callable(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "catalog_server.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('catalog')\n"
        "@mcp.tool\n"
        "def inspect_console(url: str, limit: int = 20) -> str:\n"
        "    'Inspect browser console messages for a URL.'\n"
        "    return f'{url}:{limit}'\n"
        "@mcp.tool\n"
        "def take_screenshot() -> str:\n"
        "    'Capture the current browser page.'\n"
        "    return 'shot'\n"
        "mcp.run(transport='stdio')\n"
    )
    config = tmp_path / "mcp.json"
    _write_config(config, {
        "chrome-devtools": {
            "command": sys.executable,
            "args": [str(server_script)],
            "toolPrefix": "chrome",
        }
    })
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        tool_exposure_mode="discover",
    )

    async def scenario():
        await manager.start(gateway)
        try:
            exposed = {tool.name for tool in await gateway.list_tools()}
            found = manager.search_tools("chrome browser console errors", server_name="chrome-devtools")
            read = manager.read_tool("chrome-devtools", "inspect_console")
            called = await manager.call_tool(
                "chrome-devtools",
                "inspect_console",
                {"url": "https://example.test", "limit": 3},
            )
            return exposed, found, read, called
        finally:
            await manager.close()

    exposed, found, read, called = asyncio.run(scenario())

    assert "chrome_inspect_console" not in exposed
    assert found["matches"][0]["server"] == "chrome-devtools"
    assert found["matches"][0]["name"] == "inspect_console"
    assert "browser console" in found["matches"][0]["description"].lower()
    assert "inputSchema" not in found["matches"][0]
    assert "outputSchema" not in found["matches"][0]
    assert read["inputSchema"]["required"] == ["url"]
    assert read["inputSchema"]["properties"]["limit"]["default"] == 20
    assert called["content"][0]["text"] == "https://example.test:3"


def test_registry_defaults_to_discover_mode(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "echo", "ok"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        await manager.start(gateway)
        try:
            return {tool.name for tool in await gateway.list_tools()}, manager.registry.tool_exposure_mode
        finally:
            await manager.close()

    exposed, mode = asyncio.run(scenario())
    assert mode == "discover"
    assert "demo_echo" not in exposed


def test_search_matches_historical_prefixed_tool_name(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {
        "demo": {
            "command": sys.executable,
            "args": [str(script), "secret_tool", "ok"],
            "toolPrefix": "svc",
        }
    })
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        tool_exposure_mode="discover",
    )

    async def scenario():
        await manager.start(gateway)
        try:
            return manager.search_tools("svc_secret_tool")
        finally:
            await manager.close()

    found = asyncio.run(scenario())
    assert found["total"] == 1
    assert found["matches"][0]["name"] == "secret_tool"


def test_discover_call_survives_concurrent_registry_reload(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "slow_server.py"
    server_script.write_text(
        "import sys, time\n"
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('slow')\n"
        "name, value = sys.argv[1], sys.argv[2]\n"
        "def handler(delay: float = 0.2) -> str:\n"
        "    time.sleep(delay)\n"
        "    return value\n"
        "mcp.tool(name=name)(handler)\n"
        "mcp.run(transport='stdio')\n"
    )
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(server_script), "slow", "old"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        tool_exposure_mode="discover",
    )

    async def scenario():
        await manager.start(gateway)
        try:
            call = asyncio.create_task(manager.call_tool("demo", "slow", {"delay": 1.2}))
            await asyncio.sleep(0.05)
            _write_config(config, {"demo": {"command": sys.executable, "args": [str(server_script), "fast", "new"]}})
            refreshed = asyncio.create_task(manager.refresh())
            called = await call
            diff = await refreshed
            found = manager.search_tools("fast")
            return called, diff, found
        finally:
            await manager.close()

    called, diff, found = asyncio.run(scenario())
    assert called["content"][0]["text"] == "old"
    assert diff.changed_servers == {"demo"}
    assert found["matches"][0]["name"] == "fast"
