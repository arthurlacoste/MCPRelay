import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def gateway_snapshot(overrides: dict[str, str], script_body: str) -> dict:
    env = os.environ.copy()
    env.update(overrides)
    env["PYTHONPATH"] = str(ROOT / "src")
    script = f"""
import asyncio, json, sys, time
from fastmcp import Client
import mcp_gateway as mod

async def snapshot():
    async with Client(mod.mcp) as client:
        tools = [tool.name for tool in await client.list_tools()]
    {script_body}

asyncio.run(snapshot())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def test_no_realtime_uses_blocking_contract_and_hides_queue_tools():
    snapshot = gateway_snapshot(
        {"MCP_REALTIME_STATUS_ENABLED": "false"},
        """
        started = time.monotonic()
        output = mod.run_command(
            command=f'"{sys.executable}" -c "import time; time.sleep(.1); print(\\'done\\')"'
        )
        print(json.dumps({
            'tools': tools,
            'output': output,
            'elapsed': time.monotonic() - started,
            'queue_is_none': mod.command_queue is None,
        }))
        """,
    )

    assert snapshot["elapsed"] >= 0.1
    assert "STDOUT:\ndone" in snapshot["output"]
    assert snapshot["queue_is_none"] is True
    assert "get_queue_state" not in snapshot["tools"]
    assert "get_command_state" not in snapshot["tools"]
    assert "stop_command" not in snapshot["tools"]


def test_widget_enables_realtime_mode():
    snapshot = gateway_snapshot(
        {
            "MCP_REALTIME_STATUS_ENABLED": "false",
            "MCP_WIDGET_ENABLED": "true",
        },
        """
        resources = []
        async with Client(mod.mcp) as client:
            resources = [str(resource.uri) for resource in await client.list_resources()]
        print(json.dumps({
            'resources': resources,
            'widget': mod.RUNTIME_FEATURES.widget_enabled,
            'realtime': mod.RUNTIME_FEATURES.realtime_enabled,
        }))
        """,
    )

    assert snapshot["widget"] is True
    assert snapshot["realtime"] is True
    assert "ui://mcprelay/terminal.html" in snapshot["resources"]
