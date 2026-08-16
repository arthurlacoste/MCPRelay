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

    signal_file = tmp_path / "handler_started.signal"
    server_script = tmp_path / "slow_server.py"
    server_script.write_text(
        "import sys, time\n"
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('slow')\n"
        "name, value, signal_path = sys.argv[1], sys.argv[2], sys.argv[3]\n"
        "def handler(delay: float = 0.2) -> str:\n"
        "    open(signal_path, 'w').close()\n"
        "    time.sleep(delay)\n"
        "    return value\n"
        "mcp.tool(name=name)(handler)\n"
        "mcp.run(transport='stdio')\n"
    )
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(server_script), "slow", "old", str(signal_file)]}})
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
            # Wait for handler to actually start (signal file created)
            timeout = 5.0
            start = asyncio.get_event_loop().time()
            while not signal_file.exists():
                if asyncio.get_event_loop().time() - start > timeout:
                    raise TimeoutError("Handler did not start within timeout")
                await asyncio.sleep(0.01)
            _write_config(config, {"demo": {"command": sys.executable, "args": [str(server_script), "fast", "new", str(signal_file)]}})
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


def test_invalid_registry_exposure_mode_falls_back_to_discover(tmp_path, caplog):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    with caplog.at_level("WARNING"):
        manager = MCPProxyManager(
            config,
            project_root=tmp_path,
            environ={},
            refresh_interval_seconds=0,
            tool_exposure_mode="ful",
        )

    assert manager.registry.tool_exposure_mode == "discover"
    assert "discover" in caplog.text


def test_historical_public_name_gets_exact_match_ranking(tmp_path):
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {
        "alpha": {
            "command": sys.executable,
            "args": [str(script), "secret_tool", "one"],
            "toolPrefix": "svc",
        },
        "beta": {
            "command": sys.executable,
            "args": [str(script), "svc_secret_tool_helper", "two"],
            "toolPrefix": "other",
        },
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
    assert found["matches"][0]["server"] == "alpha"
    assert found["matches"][0]["name"] == "secret_tool"


def test_manual_refresh_requests_are_coalesced(tmp_path, monkeypatch):
    from mcp_proxy import MCPProxyManager
    from mcp_registry import RegistryDiff

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_refresh():
        started.set()
        await release.wait()
        return RegistryDiff()

    monkeypatch.setattr(manager.registry, "refresh", slow_refresh)

    async def scenario():
        first = manager.request_refresh()
        await started.wait()
        second = manager.request_refresh()
        release.set()
        await manager.registry._manual_refresh_task
        return first, second

    first, second = asyncio.run(scenario())
    assert first == {"status": "scheduled"}
    assert second == {"status": "running"}


def test_call_tool_stops_after_two_stale_catalog_retries(tmp_path):
    from types import SimpleNamespace
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)
    registry = manager.registry

    class SwapLock:
        def __init__(self, replacement):
            self.replacement = replacement

        async def __aenter__(self):
            registry.states["demo"] = self.replacement

        async def __aexit__(self, exc_type, exc, tb):
            return False

    state3 = SimpleNamespace(status="healthy", proxy=object(), catalog_tools={"echo": object()}, call_lock=None)
    state2 = SimpleNamespace(status="healthy", proxy=object(), catalog_tools={"echo": object()}, call_lock=SwapLock(state3))
    state1 = SimpleNamespace(status="healthy", proxy=object(), catalog_tools={"echo": object()}, call_lock=SwapLock(state2))
    registry.states["demo"] = state1

    result = asyncio.run(manager.call_tool("demo", "echo"))

    assert result == {"error": "catalog_changed", "server": "demo", "name": "echo"}


def test_close_cancels_pending_manual_refresh_before_state_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from mcp_proxy import MCPProxyManager
    from mcp_registry import RegistryDiff

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)
    registry = manager.registry
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def delayed_refresh():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        registry.states["late"] = SimpleNamespace()
        return RegistryDiff()

    monkeypatch.setattr(registry, "refresh", delayed_refresh)

    async def scenario():
        manager.request_refresh()
        await started.wait()
        await manager.close()
        await asyncio.sleep(0)
        assert cancelled.is_set()
        assert registry.states == {}
        assert registry._manual_refresh_task.done()
        assert manager.request_refresh() == {"status": "closed"}

    asyncio.run(scenario())


def test_registry_reads_tool_exposure_mode_from_environ_when_not_explicit(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={"MCP_TOOL_EXPOSURE_MODE": "full"},
        refresh_interval_seconds=0,
    )

    assert manager.registry.tool_exposure_mode == "full"


def test_manual_refresh_status_records_global_config_failure(tmp_path):
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)

    async def scenario():
        gateway = FastMCP("gateway")
        await manager.start(gateway)
        config.write_text('{"mcpServers": ')
        scheduled = manager.request_refresh()
        await manager.registry._manual_refresh_task
        status = manager.refresh_status()
        await manager.close()
        return scheduled, status

    scheduled, status = asyncio.run(scenario())

    assert scheduled == {"status": "scheduled"}
    assert status["status"] == "failed"
    assert "JSONDecodeError" in status["error"]
    assert status["finished_at"].endswith("Z")


def test_cancelled_reload_closes_uninstalled_client(tmp_path, monkeypatch):
    import pytest
    import mcp_registry as registry_module
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable}})
    gateway = FastMCP("gateway")
    entered = asyncio.Event()
    clients = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.closed = False
            clients.append(self)

        async def __aenter__(self):
            return self

        async def close(self):
            self.closed = True

    class BlockingProxy:
        async def list_tools(self):
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(registry_module, "StatefulProxyClient", FakeClient)
    monkeypatch.setattr(registry_module, "create_proxy", lambda client, name: BlockingProxy())

    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        tool_exposure_mode="discover",
    )

    async def scenario():
        task = asyncio.create_task(manager.start(gateway))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert len(clients) == 1
    assert clients[0].closed is True
    assert "demo" not in manager.registry.states


def test_close_does_not_wait_forever_for_inflight_discover_call(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import mcp_registry as registry_module
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)
    registry = manager.registry
    gateway = FastMCP("gateway")
    registry.gateway = gateway
    lock = asyncio.Lock()
    closed = asyncio.Event()

    class FakeClient:
        async def close(self):
            closed.set()

    state = SimpleNamespace(
        name="demo",
        prefix="demo",
        client=FakeClient(),
        provider=None,
        call_lock=lock,
    )
    registry.states["demo"] = state
    monkeypatch.setattr(registry_module, "CLIENT_DRAIN_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(registry_module, "CLIENT_CLOSE_TIMEOUT_SECONDS", 0.1)

    async def scenario():
        await lock.acquire()
        try:
            await asyncio.wait_for(manager.close(), timeout=0.25)
        finally:
            if lock.locked():
                lock.release()

    asyncio.run(scenario())

    assert closed.is_set()
    assert registry.states == {}


def test_reload_does_not_wait_forever_for_old_inflight_call(tmp_path, monkeypatch):
    import mcp_registry as registry_module
    from mcp_proxy import MCPProxyManager

    script = _server_script(tmp_path)
    config = tmp_path / "mcp.json"
    _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "old", "old"]}})
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config,
        project_root=tmp_path,
        environ={},
        refresh_interval_seconds=0,
        tool_exposure_mode="discover",
    )
    monkeypatch.setattr(registry_module, "CLIENT_DRAIN_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(registry_module, "CLIENT_CLOSE_TIMEOUT_SECONDS", 0.2)

    async def scenario():
        await manager.start(gateway)
        old_state = manager.registry.states["demo"]
        await old_state.call_lock.acquire()
        try:
            _write_config(config, {"demo": {"command": sys.executable, "args": [str(script), "new", "new"]}})
            diff = await asyncio.wait_for(manager.refresh(), timeout=1.0)
            return diff, manager.registry.states["demo"] is old_state
        finally:
            if old_state.call_lock.locked():
                old_state.call_lock.release()
            await manager.close()

    diff, kept_old_state = asyncio.run(scenario())

    assert diff.changed_servers == {"demo"}
    assert kept_old_state is False


def test_bounded_client_close_finishes_cleanup_before_propagating_cancellation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import pytest
    import mcp_registry as registry_module
    from mcp_proxy import MCPProxyManager

    config = tmp_path / "mcp.json"
    _write_config(config, {})
    manager = MCPProxyManager(config, project_root=tmp_path, environ={}, refresh_interval_seconds=0)
    registry = manager.registry
    lock = asyncio.Lock()
    closed = asyncio.Event()

    class FakeClient:
        async def close(self):
            closed.set()

    state = SimpleNamespace(name="demo", client=FakeClient(), call_lock=lock)
    monkeypatch.setattr(registry_module, "CLIENT_DRAIN_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(registry_module, "CLIENT_CLOSE_TIMEOUT_SECONDS", 0.1)

    async def scenario():
        await lock.acquire()
        task = asyncio.create_task(registry._close_state_client(state))
        await asyncio.sleep(0)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.25)
        finally:
            if lock.locked():
                lock.release()

    asyncio.run(scenario())

    assert closed.is_set()
