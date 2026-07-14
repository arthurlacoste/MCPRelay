import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from terminal_app import TERMINAL_APP_HTML, TERMINAL_APP_URI
from tool_registry import configurable_tool


def test_terminal_widget_contains_queue_terminal_and_recovery_controls():
    assert 'MCPRelay Live Queue' in TERMINAL_APP_HTML
    assert 'Relancer' in TERMINAL_APP_HTML
    assert 'Vider' in TERMINAL_APP_HTML
    assert 'get_queue_state' in TERMINAL_APP_HTML
    assert 'get_command_state' in TERMINAL_APP_HTML
    assert 'get_command_log' in TERMINAL_APP_HTML
    assert 'stop_command' in TERMINAL_APP_HTML
    assert '750' in TERMINAL_APP_HTML
    assert '2000' in TERMINAL_APP_HTML
    assert 'stdout' in TERMINAL_APP_HTML
    assert 'stderr' in TERMINAL_APP_HTML
    assert 'Copy' in TERMINAL_APP_HTML
    assert 'Open logs' in TERMINAL_APP_HTML


def test_configurable_tool_forwards_app_metadata():
    calls = []

    class FakeMCP:
        def tool(self, **kwargs):
            calls.append(kwargs)
            return lambda fn: fn

    @configurable_tool(FakeMCP(), app={'resourceUri': 'ui://terminal/app.html'}, title='Terminal')
    def enabled_tool():
        return None

    assert calls == [{'app': {'resourceUri': 'ui://terminal/app.html'}, 'title': 'Terminal'}]
