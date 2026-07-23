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


def test_no_queue_uses_blocking_contract_and_updates_realtime_monitor():
    snapshot = gateway_snapshot(
        {"MCP_COMMAND_QUEUE_ENABLED": "false"},
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
            'calls': mod.realtime_store.snapshot()['calls'],
        }))
        """,
    )

    assert snapshot["elapsed"] >= 0.1
    assert "STDOUT:\ndone" in snapshot["output"]
    assert snapshot["queue_is_none"] is True
    assert snapshot["calls"][0]["status"] == "success"
    assert snapshot["calls"][0]["preview"].endswith("print('done')\"")
    assert "get_queue_state" not in snapshot["tools"]
    assert "get_command_state" not in snapshot["tools"]
    assert "stop_command" not in snapshot["tools"]


def test_widget_enables_queue_mode():
    snapshot = gateway_snapshot(
        {
            "MCP_COMMAND_QUEUE_ENABLED": "false",
            "MCP_WIDGET_ENABLED": "true",
        },
        """
        resources = []
        async with Client(mod.mcp) as client:
            resources = [str(resource.uri) for resource in await client.list_resources()]
        print(json.dumps({
            'resources': resources,
            'widget': mod.RUNTIME_FEATURES.widget_enabled,
            'queue': mod.RUNTIME_FEATURES.command_queue_enabled,
        }))
        """,
    )

    assert snapshot["widget"] is True
    assert snapshot["queue"] is True
    assert "ui://gate/terminal.html" in snapshot["resources"]
