import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
import mcp_gateway as mod
from terminal_app import TERMINAL_APP_URI


def test_terminal_template_is_hidden_by_default_but_realtime_tools_remain():
    async def scenario():
        async with Client(mod.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            resources = {str(resource.uri): resource for resource in await client.list_resources()}
            return tools, resources

    tools, resources = asyncio.run(scenario())
    assert 'openai/outputTemplate' not in tools['run_command'].meta
    assert 'ui' not in tools['run_command'].meta
    assert 'get_queue_state' in tools
    assert TERMINAL_APP_URI not in resources


def test_terminal_template_is_protocol_visible_when_widget_enabled():
    script = """
import asyncio, json
from fastmcp import Client
import mcp_gateway as mod

async def main():
    async with Client(mod.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        resources = {str(resource.uri): resource for resource in await client.list_resources()}
        print(json.dumps({
            'tool_meta': tools['run_command'].meta,
            'resources': list(resources),
        }))

asyncio.run(main())
"""
    env = os.environ.copy()
    env["MCP_WIDGET_ENABLED"] = "true"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    snapshot = json.loads(result.stdout.splitlines()[-1])

    assert snapshot["tool_meta"]["openai/outputTemplate"] == TERMINAL_APP_URI
    assert snapshot["tool_meta"]["ui"]["resourceUri"] == TERMINAL_APP_URI
    assert TERMINAL_APP_URI in snapshot["resources"]
