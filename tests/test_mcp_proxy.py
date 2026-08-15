import json
import logging
import asyncio
import socket
import sys
from contextlib import suppress
from time import monotonic

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_http_headers


def test_loads_classic_mcp_config_with_interpolation_and_safe_prefix(tmp_path):
    from mcp_proxy import load_proxy_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "Computer-Use": {
                "command": "${COMPUTER_USE_BIN}",
                "args": ["mcp"],
            }
        }
    }))

    servers = load_proxy_config(
        config_path,
        project_root=tmp_path,
        environ={"COMPUTER_USE_BIN": "/opt/computer-use"},
    )

    assert len(servers) == 1
    assert servers[0].name == "Computer-Use"
    assert servers[0].prefix == "computer_use"
    assert servers[0].config["command"] == "/opt/computer-use"


def test_disabled_servers_are_omitted_and_relative_cwd_uses_project_root(tmp_path):
    from mcp_proxy import load_proxy_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "off": {"command": "off", "enabled": False},
            "on": {"command": "on", "cwd": "workspace"},
        }
    }))

    servers = load_proxy_config(config_path, project_root=tmp_path, environ={})

    assert [server.name for server in servers] == ["on"]
    assert servers[0].config["cwd"] == str(tmp_path / "workspace")


def test_server_with_missing_environment_variable_is_omitted_without_logging_secrets(tmp_path, caplog):
    from mcp_proxy import load_proxy_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "broken": {"command": "${MISSING_SECRET}"},
            "healthy": {"command": "healthy"},
        }
    }))

    with caplog.at_level(logging.ERROR):
        servers = load_proxy_config(config_path, project_root=tmp_path, environ={})

    assert [server.name for server in servers] == ["healthy"]
    assert "broken" in caplog.text
    assert "MISSING_SECRET" in caplog.text
    assert "${MISSING_SECRET}" not in caplog.text


def test_missing_or_invalid_config_leaves_gateway_without_proxies(tmp_path, caplog):
    from mcp_proxy import load_proxy_config

    missing = load_proxy_config(tmp_path / "missing.json", project_root=tmp_path, environ={})
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not json")
    invalid = load_proxy_config(invalid_path, project_root=tmp_path, environ={})

    assert missing == []
    assert invalid == []
    assert "missing.json" in caplog.text
    assert "invalid.json" in caplog.text


def test_structurally_invalid_config_is_ignored(tmp_path, caplog):
    from mcp_proxy import load_proxy_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text("[]")

    servers = load_proxy_config(config_path, project_root=tmp_path, environ={})

    assert servers == []
    assert "mcpServers" in caplog.text


def test_manager_exposes_enabled_stdio_tools_with_namespace(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "server.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('fixture')\n"
        "@mcp.tool\n"
        "def echo(text: str) -> str: return text\n"
        "@mcp.tool\n"
        "def hidden() -> str: return 'hidden'\n"
        "mcp.run(transport='stdio')\n"
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "fixture-server": {
                "command": sys.executable,
                "args": [str(server_script)],
                "tools": {"hidden": {"enabled": False}},
            }
        }
    }))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            tools = await gateway.list_tools()
            result = await gateway.call_tool("fixture_server_echo", {"text": "hello"})
            hidden_search = manager.search_tools("hidden")
            hidden_read = manager.read_tool("fixture-server", "hidden")
            hidden_call = await manager.call_tool("fixture-server", "hidden")
            return tools, result, hidden_search, hidden_read, hidden_call
        finally:
            await manager.close()

    tools, result, hidden_search, hidden_read, hidden_call = asyncio.run(scenario())

    assert [tool.name for tool in tools] == ["fixture_server_echo"]
    assert result.content[0].text == "hello"
    assert hidden_search["total"] == 0
    assert hidden_read["error"] == "tool_not_found"
    assert hidden_call["error"] == "tool_not_found"


def test_unavailable_server_is_omitted_without_blocking_native_tools(tmp_path, caplog):
    from mcp_proxy import MCPProxyManager

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {"broken": {"command": "/missing/mcp-server"}}
    }))
    gateway = FastMCP("gateway")

    @gateway.tool
    def native() -> str:
        return "ok"

    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            return await gateway.list_tools()
        finally:
            await manager.close()

    tools = asyncio.run(scenario())

    assert [tool.name for tool in tools] == ["native"]
    assert "broken" in caplog.text


def test_proxied_calls_emit_technical_log_without_arguments(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "server.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('fixture')\n"
        "@mcp.tool\n"
        "def echo(secret: str) -> str: return secret\n"
        "mcp.run(transport='stdio')\n"
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {"fixture": {"command": sys.executable, "args": [str(server_script)]}}
    }))
    events = []
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config_path,
        project_root=tmp_path,
        environ={},
        event_logger=lambda action, payload: events.append((action, payload)),
        tool_exposure_mode="full",
    )

    async def scenario():
        await manager.start(gateway)
        try:
            await gateway.call_tool("fixture_echo", {"secret": "do-not-log"})
        finally:
            await manager.close()

    asyncio.run(scenario())

    proxy_event = next(payload for action, payload in events if action == "mcp_proxy_call")
    assert proxy_event["server"] == "fixture"
    assert proxy_event["tool"] == "echo"
    assert proxy_event["status"] == "success"
    assert "duration_ms" in proxy_event
    assert "do-not-log" not in repr(events)


def test_proxy_namespaces_resources_templates_and_prompts(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "components.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('components')\n"
        "@mcp.resource('data://status')\n"
        "def status() -> str: return 'ready'\n"
        "@mcp.resource('data://items/{item_id}')\n"
        "def item(item_id: str) -> str: return item_id\n"
        "@mcp.prompt\n"
        "def greet(name: str) -> str: return f'Hello {name}'\n"
        "mcp.run(transport='stdio')\n"
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {"components": {"command": sys.executable, "args": [str(server_script)]}}
    }))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            return (
                await gateway.list_resources(),
                await gateway.list_resource_templates(),
                await gateway.list_prompts(),
            )
        finally:
            await manager.close()

    resources, templates, prompts = asyncio.run(scenario())

    assert [str(resource.uri) for resource in resources] == ["data://components/status"]
    assert [template.uri_template for template in templates] == ["data://components/items/{item_id}"]
    assert [prompt.name for prompt in prompts] == ["components_greet"]


def test_proxied_failures_emit_error_log(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "failure.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('failure')\n"
        "@mcp.tool\n"
        "def fail() -> str: raise RuntimeError('boom')\n"
        "mcp.run(transport='stdio')\n"
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {"failure": {"command": sys.executable, "args": [str(server_script)]}}
    }))
    events = []
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(
        config_path,
        project_root=tmp_path,
        environ={},
        event_logger=lambda action, payload: events.append((action, payload)),
        tool_exposure_mode="full",
    )

    async def scenario():
        await manager.start(gateway)
        try:
            with pytest.raises(Exception):
                await gateway.call_tool("failure_fail", {})
        finally:
            await manager.close()

    asyncio.run(scenario())

    proxy_event = next(payload for action, payload in events if action == "mcp_proxy_call")
    assert proxy_event["status"] == "error"
    assert "boom" not in repr(events)


def test_initialization_timeout_omits_stalled_server_quickly(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "stalled.py"
    server_script.write_text("import time\ntime.sleep(10)\n")
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "stalled": {
                "command": sys.executable,
                "args": [str(server_script)],
                "initTimeoutMs": 50,
            }
        }
    }))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    started = monotonic()
    asyncio.run(manager.start(gateway))
    elapsed = monotonic() - started
    asyncio.run(manager.close())

    assert elapsed < 1
    assert asyncio.run(gateway.list_tools()) == []


def test_namespace_collision_keeps_first_server(tmp_path, caplog):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "server.py"
    server_script.write_text(
        "from fastmcp import FastMCP\n"
        "mcp = FastMCP('fixture')\n"
        "@mcp.tool\n"
        "def echo() -> str: return 'first'\n"
        "mcp.run(transport='stdio')\n"
    )
    entry = {"command": sys.executable, "args": [str(server_script)]}
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {"same-name": entry, "same_name": entry}
    }))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            return await gateway.list_tools()
        finally:
            await manager.close()

    tools = asyncio.run(scenario())

    assert [tool.name for tool in tools] == ["same_name_echo"]
    assert "same_name" in caplog.text
    assert "namespace collision" in caplog.text


def test_http_proxy_uses_configured_headers_without_forwarding_gateway_authorization(tmp_path):
    from mcp_proxy import MCPProxyManager

    downstream = FastMCP("downstream")

    @downstream.tool
    def headers() -> dict[str, str]:
        return get_http_headers(include_all=True)

    gateway = FastMCP("gateway")

    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    downstream_port = free_port()
    gateway_port = free_port()
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "remote": {
                "url": f"http://127.0.0.1:{downstream_port}/mcp",
                "transport": "http",
                "headers": {"x-configured": "yes"},
            }
        }
    }))
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def wait_for_port(port: int) -> None:
        for _ in range(100):
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                await asyncio.sleep(0.01)
                continue
            writer.close()
            await writer.wait_closed()
            return
        raise TimeoutError(f"port {port} did not open")

    async def scenario():
        downstream_task = asyncio.create_task(downstream.run_async(
            transport="http", host="127.0.0.1", port=downstream_port, path="/mcp", show_banner=False,
        ))
        await wait_for_port(downstream_port)
        await manager.start(gateway)
        gateway_task = asyncio.create_task(gateway.run_async(
            transport="http", host="127.0.0.1", port=gateway_port, path="/mcp", show_banner=False,
        ))
        await wait_for_port(gateway_port)
        transport = StreamableHttpTransport(
            f"http://127.0.0.1:{gateway_port}/mcp",
            headers={"authorization": "Bearer gateway-secret"},
        )
        try:
            async with Client(transport) as client:
                result = await client.call_tool("remote_headers", {})
                return json.loads(result.content[0].text)
        finally:
            await manager.close()
            gateway_task.cancel()
            downstream_task.cancel()
            with suppress(asyncio.CancelledError):
                await gateway_task
            with suppress(asyncio.CancelledError):
                await downstream_task

    observed = asyncio.run(scenario())

    assert observed["x-configured"] == "yes"
    assert "authorization" not in observed


def test_sse_server_config_is_preserved(tmp_path):
    from mcp_proxy import load_proxy_config

    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "events": {
                "url": "https://example.test/sse",
                "transport": "sse",
                "auth": "${REMOTE_TOKEN}",
            }
        }
    }))

    servers = load_proxy_config(
        config_path,
        project_root=tmp_path,
        environ={"REMOTE_TOKEN": "secret-token"},
    )

    assert servers[0].config == {
        "url": "https://example.test/sse",
        "transport": "sse",
        "auth": "secret-token",
    }


def test_gateway_no_longer_exposes_legacy_downstream_or_desktop_tools():
    import mcp_gateway

    removed = {
        "list_filesystem_available_tools",
        "filesystem_execute_tool",
        "list_puppeteer_available_tools",
        "puppeteer_execute_tool",
        "vision_screen_size",
        "vision_screenshot",
        "vision_screenshot_as_base64",
        "mouse_position",
        "mouse_move",
        "mouse_click_at",
        "mouse_click_current",
        "mouse_drag",
        "mouse_scroll",
        "keyboard_type",
        "keyboard_press",
        "keyboard_hotkey",
    }

    exposed = {tool.name for tool in asyncio.run(mcp_gateway.mcp.list_tools())}

    assert removed.isdisjoint(exposed)


def test_proxy_reuses_single_initialized_stdio_session(tmp_path):
    from mcp_proxy import MCPProxyManager

    server_script = tmp_path / "strict_server.py"
    server_script.write_text(
        "import json, sys\n"
        "initialized = False\n"
        "for line in sys.stdin:\n"
        "    message = json.loads(line)\n"
        "    method = message.get('method')\n"
        "    if method == 'initialize':\n"
        "        if initialized:\n"
        "            response = {'jsonrpc':'2.0','id':message['id'],'error':{'code':-32600,'message':'Server is already initialized'}}\n"
        "        else:\n"
        "            initialized = True\n"
        "            response = {'jsonrpc':'2.0','id':message['id'],'result':{'protocolVersion':message['params']['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'strict','version':'1'}}}\n"
        "    elif method == 'tools/list':\n"
        "        response = {'jsonrpc':'2.0','id':message['id'],'result':{'tools':[{'name':'echo','description':'echo','inputSchema':{'type':'object','properties':{}}}]}}\n"
        "    elif method == 'tools/call':\n"
        "        response = {'jsonrpc':'2.0','id':message['id'],'result':{'content':[{'type':'text','text':'ok'}]}}\n"
        "    else:\n"
        "        continue\n"
        "    print(json.dumps(response), flush=True)\n"
    )
    config_path = tmp_path / "mcp.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "strict": {"command": sys.executable, "args": [str(server_script)]}
        }
    }))
    gateway = FastMCP("gateway")
    manager = MCPProxyManager(config_path, project_root=tmp_path, environ={}, tool_exposure_mode="full")

    async def scenario():
        await manager.start(gateway)
        try:
            tools = await gateway.list_tools()
            result = await gateway.call_tool("strict_echo", {})
            return tools, result
        finally:
            await manager.close()

    tools, result = asyncio.run(scenario())

    assert [tool.name for tool in tools] == ["strict_echo"]
    assert result.content[0].text == "ok"


def test_gateway_defaults_to_seven_discovery_tools(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers": {}}')
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    empty_config = tmp_path / "empty-config"
    empty_config.mkdir()
    env["MCP_CONFIG_ROOT"] = str(empty_config)
    env["MCP_SERVERS_CONFIG"] = str(config)
    env["ENABLE_OAUTH"] = "false"
    env["MCP_COMMAND_QUEUE_ENABLED"] = "false"
    env.pop("MCP_TOOL_EXPOSURE_MODE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio,json,mcp_gateway; print(json.dumps(sorted(t.name for t in asyncio.run(mcp_gateway.mcp.list_tools()))))",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(result.stdout.strip().splitlines()[-1]) == [
        "mcp_servers_list",
        "mcp_tool_call",
        "mcp_tool_read",
        "mcp_tools_search",
        "run_command",
        "skills_read",
        "skills_search",
    ]


def test_discover_mode_keeps_queue_helpers_when_queue_is_enabled(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers": {}}')
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    empty_config = tmp_path / "empty-config"
    empty_config.mkdir()
    env["MCP_CONFIG_ROOT"] = str(empty_config)
    env["MCP_SERVERS_CONFIG"] = str(config)
    env["ENABLE_OAUTH"] = "false"
    env["MCP_TOOL_EXPOSURE_MODE"] = "discover"
    env["MCP_COMMAND_QUEUE_ENABLED"] = "true"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio,json,mcp_gateway; print(json.dumps(sorted(t.name for t in asyncio.run(mcp_gateway.mcp.list_tools()))))",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    names = set(json.loads(result.stdout.strip().splitlines()[-1]))

    assert {
        "run_command",
        "get_queue_state",
        "get_command_state",
        "get_command_output",
        "get_command_log",
        "stop_command",
        "resolve_command_recovery",
    } <= names


def test_mcp_servers_list_can_schedule_registry_refresh(monkeypatch):
    import mcp_gateway

    events = []
    monkeypatch.setattr(
        mcp_gateway.proxy_manager,
        "request_refresh",
        lambda: events.append("refresh") or {"status": "scheduled"},
    )
    monkeypatch.setattr(mcp_gateway.proxy_manager, "list_servers", lambda: [{"name": "new", "status": "healthy"}])

    result = asyncio.run(mcp_gateway.mcp_servers_list(refresh=True))

    assert events == ["refresh"]
    assert result["servers"] == [{"name": "new", "status": "healthy"}]
    assert result["refresh"] == {"status": "scheduled"}


def test_gateway_invalid_exposure_mode_falls_back_to_discover(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    config = tmp_path / "mcp.json"
    config.write_text('{"mcpServers": {}}')
    empty_config = tmp_path / "empty-config"
    empty_config.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["MCP_CONFIG_ROOT"] = str(empty_config)
    env["MCP_SERVERS_CONFIG"] = str(config)
    env["ENABLE_OAUTH"] = "false"
    env["MCP_COMMAND_QUEUE_ENABLED"] = "false"
    env["MCP_TOOL_EXPOSURE_MODE"] = "ful"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio,json,mcp_gateway; print(json.dumps(sorted(t.name for t in asyncio.run(mcp_gateway.mcp.list_tools()))))",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    names = json.loads(result.stdout.strip().splitlines()[-1])
    assert names == [
        "mcp_servers_list",
        "mcp_tool_call",
        "mcp_tool_read",
        "mcp_tools_search",
        "run_command",
        "skills_read",
        "skills_search",
    ]
    assert "falling back to 'discover'" in result.stderr
