import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
import mcp_gateway as mod


def isolated_dirs(tmp_path):
    mod.CONVERSATION_DIR = tmp_path
    mod.STREAM_DIR = tmp_path


async def call(command: str, timeout_seconds: float = 5):
    async with Client(mod.mcp) as client:
        started = time.perf_counter()
        result = await asyncio.wait_for(
            client.call_tool('run_command', {
                'command': command,
                'timeout_seconds': timeout_seconds,
            }),
            timeout=timeout_seconds + 3,
        )
        return time.perf_counter() - started, str(result)


def test_fastmcp_run_command_returns(tmp_path):
    isolated_dirs(tmp_path)
    elapsed, result = asyncio.run(call(f'"{sys.executable}" -c "print(\'ok\')"'))
    assert elapsed < 2
    assert 'ok' in result


def test_slow_command_does_not_block_lightweight_tool(tmp_path):
    isolated_dirs(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            slow = asyncio.create_task(client.call_tool('run_command', {
                'command': f'"{sys.executable}" -c "import time; time.sleep(0.8)"',
            }))
            await asyncio.sleep(0.05)
            started = time.perf_counter()
            await client.call_tool('conversation_start', {})
            ping_elapsed = time.perf_counter() - started
            await slow
            return ping_elapsed

    assert asyncio.run(scenario()) < 0.25


def test_commands_run_concurrently(tmp_path):
    isolated_dirs(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            command = f'"{sys.executable}" -c "import time; time.sleep(0.3)"'
            started = time.perf_counter()
            await asyncio.gather(*[
                client.call_tool('run_command', {'command': command})
                for _ in range(4)
            ])
            return time.perf_counter() - started

    assert asyncio.run(scenario()) < 0.9


def test_noop_latency_stays_low_without_folder_scan(tmp_path):
    isolated_dirs(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            samples = []
            command = f'"{sys.executable}" -c "pass"'
            for _ in range(8):
                started = time.perf_counter()
                await client.call_tool('run_command', {'command': command})
                samples.append(time.perf_counter() - started)
            return statistics.median(samples)

    assert asyncio.run(scenario()) < 0.1
