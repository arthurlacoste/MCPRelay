import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
from command_queue import CommandQueue
import mcp_gateway as mod


def install_queue(tmp_path):
    mod.command_queue.close()
    mod.command_queue = CommandQueue(tmp_path / 'commands.sqlite3', tmp_path, worker_limit=4, on_event=mod.command_finished)


async def tool(client, name, arguments):
    result = await client.call_tool(name, arguments)
    return result.structured_content or result.data


def test_fastmcp_run_command_returns_immediately(tmp_path):
    install_queue(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            started = time.perf_counter()
            result = await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "import time; time.sleep(.5); print(\'ok\')"',
            })
            return time.perf_counter() - started, result

    elapsed, result = asyncio.run(scenario())
    assert elapsed < .25
    assert result['execution_id'].startswith('exec_')
    assert result['status'] in {'queued', 'starting', 'running'}


def test_slow_command_does_not_block_lightweight_tool(tmp_path):
    install_queue(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "import time; time.sleep(.8)"',
            })
            started = time.perf_counter()
            await client.call_tool('conversation_start', {})
            return time.perf_counter() - started

    assert asyncio.run(scenario()) < .25


def test_commands_queue_and_run_concurrently(tmp_path):
    install_queue(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            command = f'"{sys.executable}" -c "import time; time.sleep(.3)"'
            results = await asyncio.gather(*[
                tool(client, 'run_command', {'command': command}) for _ in range(5)
            ])
            state = await tool(client, 'get_queue_state', {})
            return results, state

    results, state = asyncio.run(scenario())
    assert len({result['execution_id'] for result in results}) == 5
    assert state['workers']['limit'] == 4
    assert state['queued'] >= 1


def test_state_and_output_tools_poll_by_cursor(tmp_path):
    install_queue(tmp_path)

    async def scenario():
        async with Client(mod.mcp) as client:
            run = await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "print(\'one\'); print(\'two\')"',
            })
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = await tool(client, 'get_command_state', {
                    'execution_id': run['execution_id'], 'after_cursor': 0, 'limit': 1,
                })
                if state['status'] == 'success':
                    return state, await tool(client, 'get_command_output', {
                        'execution_id': run['execution_id'], 'cursor': state['cursor'],
                    })
                await asyncio.sleep(.02)
            raise AssertionError('command did not finish')

    state, rest = asyncio.run(scenario())
    assert state['lines'][0]['text'] == 'one'
    assert rest['lines'][0]['text'] == 'two'
