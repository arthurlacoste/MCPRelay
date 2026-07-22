import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
from command_queue import CommandQueue
import mcp_gateway as mod


@pytest.fixture(autouse=True)
def close_test_queue():
    yield
    if mod.command_queue is not None:
        mod.command_queue.close()

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
            tools = {tool.name: tool for tool in await client.list_tools()}
            started = time.perf_counter()
            result = await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "import time; time.sleep(.5); print(\'ok\')"',
                'cwd': str(tmp_path),
            })
            return time.perf_counter() - started, result, tools['run_command'].inputSchema

    elapsed, result, schema = asyncio.run(scenario())
    assert elapsed < .25
    assert 'cwd' in schema['properties']
    assert result['cwd'] == str(tmp_path.resolve())
    assert result['execution_id'].startswith('exec_')
    assert result['status'] in {'queued', 'starting', 'running'}
    assert result['polling'] is True
    assert result['next_action']['tool'] == 'get_command_state'
    assert 'Do not start another command' in result['message']


def test_fast_command_returns_inline_output(tmp_path, monkeypatch):
    install_queue(tmp_path)
    monkeypatch.setattr(mod, 'REALTIME_INLINE_WAIT_SECONDS', .5)

    async def scenario():
        async with Client(mod.mcp) as client:
            return await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "print(\'inline-ok\')"',
            })

    result = asyncio.run(scenario())
    assert result['status'] == 'success'
    assert result['polling'] is False
    assert result['next_action'] is None
    assert [line['text'] for line in result['lines']] == ['inline-ok']


def test_terminal_polling_session_expires_and_logs_network_event(tmp_path, monkeypatch):
    install_queue(tmp_path)
    monkeypatch.setattr(mod, 'CONVERSATION_DIR', tmp_path / 'conversations')
    monkeypatch.setattr(mod, 'LOG_FILE', tmp_path / 'gateway.jsonl')
    monkeypatch.setattr(mod, 'TERMINAL_SESSION_TTL_SECONDS', 10)
    clock = [100.0]
    monkeypatch.setattr(mod, 'monotonic', lambda: clock[0])
    with mod.terminal_sessions_lock:
        mod.terminal_sessions.clear()

    async def scenario():
        async with Client(mod.mcp) as client:
            run = await tool(client, 'run_command', {
                'command': f'"{sys.executable}" -c "print(\'done\')"',
                'conversation_id': 'poll-expiry',
            })
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = await tool(client, 'get_command_state', {'execution_id': run['execution_id']})
                if state['status'] == 'success':
                    break
                await asyncio.sleep(.02)
            else:
                raise AssertionError('command did not finish')
            clock[0] = 111.0
            queue_state = await tool(client, 'get_queue_state', {})
            command_state = await tool(client, 'get_command_state', {'execution_id': run['execution_id']})
            return queue_state, command_state

    queue_state, command_state = asyncio.run(scenario())
    assert queue_state['status'] == 'expired'
    assert queue_state['closed'] is True
    assert queue_state['polling'] is False
    assert command_state['status'] == 'expired'
    events = [json.loads(line) for line in (tmp_path / 'conversations' / 'poll-expiry.jsonl').read_text().splitlines()]
    network_events = [event for event in events if event['type'] == 'network_error']
    assert len(network_events) == 1
    assert network_events[0]['error'] == 'mcp_network_error'
    assert network_events[0]['inferred'] is True


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
