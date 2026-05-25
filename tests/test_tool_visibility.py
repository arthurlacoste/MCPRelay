import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import mcp_gateway as mod


def test_fastmcp_list_tools_hides_disabled_tools(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'disabled': ['hidden_tool'],
        },
        'conversation': {
            'auto_start_enabled': False,
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    server = mod.ConfigAwareFastMCP('test-server')

    @server.tool()
    def visible_tool() -> str:
        return 'ok'

    @server.tool()
    def hidden_tool() -> str:
        return 'hidden'

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == ['visible_tool']


def test_downstream_available_tools_hides_disabled_alias(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'disabled': ['filesystem.read_file'],
        },
        'conversation': {
            'auto_start_enabled': False,
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    tools = [
        SimpleNamespace(name='read_file'),
        SimpleNamespace(name='list_directory'),
    ]

    assert mod.filter_available_tools(tools, 'filesystem') == [tools[1]]


def test_downstream_execute_refuses_disabled_alias(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'per_tool': {
                'filesystem_execute_tool': {'enabled': True},
            },
            'disabled': ['filesystem.read_file'],
        },
        'conversation': {
            'auto_start_enabled': False,
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    try:
        asyncio.run(mod.filesystem_execute_tool(
            name='read_file',
            arguments={},
            purpose='unit test',
        ))
    except RuntimeError as exc:
        assert 'filesystem.read_file' in str(exc)
    else:
        raise AssertionError('disabled downstream tool was executed')


def test_list_wrappers_hidden_when_execute_wrappers_are_disabled(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'per_tool': {
                'filesystem_execute_tool': {'enabled': False},
                'puppeteer_execute_tool': {'enabled': False},
            },
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    tools = [
        SimpleNamespace(name='list_filesystem_available_tools'),
        SimpleNamespace(name='list_puppeteer_available_tools'),
        SimpleNamespace(name='run_command'),
    ]

    assert mod.filter_available_tools(tools) == [tools[2]]


def test_vision_screen_size_hidden_when_vision_tools_are_disabled(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'per_tool': {
                'vision_screenshot': {'enabled': False},
                'vision_screenshot_as_base64': {'enabled': False},
            },
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    tools = [
        SimpleNamespace(name='vision_screen_size'),
        SimpleNamespace(name='run_command'),
    ]

    assert mod.filter_available_tools(tools) == [tools[1]]


def test_mouse_and_keyboard_groups_hide_related_tools(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'per_tool': {
                'mouse': {'enabled': False},
                'keyboard': {'enabled': False},
            },
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    tools = [
        SimpleNamespace(name='mouse_position'),
        SimpleNamespace(name='mouse_move'),
        SimpleNamespace(name='keyboard_type'),
        SimpleNamespace(name='keyboard_hotkey'),
        SimpleNamespace(name='run_command'),
    ]

    assert mod.filter_available_tools(tools) == [tools[4]]


def test_mouse_group_refuses_direct_tool_execution(monkeypatch):
    settings = mod.deep_merge(mod.DEFAULT_SETTINGS, {
        'tools': {
            'per_tool': {
                'mouse': {'enabled': False},
            },
        },
    })
    monkeypatch.setattr(mod, 'load_settings', lambda force=False: settings)

    try:
        asyncio.run(mod.mouse_position())
    except RuntimeError as exc:
        assert 'mouse_position' in str(exc)
    else:
        raise AssertionError('disabled mouse tool was executed')
