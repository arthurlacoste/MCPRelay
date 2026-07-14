import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from fastmcp import Client
import mcp_gateway as mod
from terminal_app import TERMINAL_APP_URI


def test_terminal_template_metadata_and_resource_are_protocol_visible():
    async def scenario():
        async with Client(mod.mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            resources = {str(resource.uri): resource for resource in await client.list_resources()}
            contents = await client.read_resource(TERMINAL_APP_URI)
            return tools, resources, contents

    tools, resources, contents = asyncio.run(scenario())
    assert tools['run_command'].meta['openai/outputTemplate'] == TERMINAL_APP_URI
    assert tools['run_command'].meta['ui']['resourceUri'] == TERMINAL_APP_URI
    assert 'get_queue_state' in tools
    assert resources[TERMINAL_APP_URI].mimeType == 'text/html;profile=mcp-app'
    assert contents[0].mimeType == 'text/html;profile=mcp-app'
    assert 'MCPRelay Live Queue' in contents[0].text
