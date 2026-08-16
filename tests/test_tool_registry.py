from pathlib import Path

from src.tool_registry import is_tool_enabled, load_tool_config


def write_config(tmp_path: Path, text: str) -> dict:
    path = tmp_path / 'tools.toml'
    path.write_text(text)
    load_tool_config.cache_clear()
    return load_tool_config(str(path))


def test_missing_config_enables_tools_by_default(tmp_path):
    load_tool_config.cache_clear()
    cfg = load_tool_config(str(tmp_path / 'missing.toml'))

    assert is_tool_enabled('run_command', cfg) is True


def test_can_disable_gateway_tool(tmp_path):
    cfg = write_config(tmp_path, '[tools]\nrun_command = false\n')

    assert is_tool_enabled('run_command', cfg) is False
    assert is_tool_enabled('public_file_list', cfg) is True


def test_invalid_tool_exposure_mode_falls_back_to_discover(caplog):
    from src.tool_registry import tool_exposure_mode

    with caplog.at_level('WARNING'):
        mode = tool_exposure_mode({'MCP_TOOL_EXPOSURE_MODE': 'ful'})

    assert mode == 'discover'
    assert 'MCP_TOOL_EXPOSURE_MODE' in caplog.text
    assert 'discover' in caplog.text


def test_disabled_tool_is_not_added_to_gate_discovery_catalog(monkeypatch, tmp_path):
    from src.gate_tool_catalog import GateToolCatalog
    from src.tool_registry import configurable_tool

    config = tmp_path / "tools.toml"
    config.write_text("[tools]\nhidden_admin = false\n")
    monkeypatch.setenv("MCP_TOOLS_CONFIG", str(config))
    monkeypatch.setenv("MCP_TOOL_EXPOSURE_MODE", "discover")
    load_tool_config.cache_clear()

    class FakeMCP:
        def __init__(self):
            self._gate_tool_catalog = GateToolCatalog()

        def tool(self, **_kwargs):
            return lambda fn: fn

    mcp = FakeMCP()

    @configurable_tool(mcp)
    def hidden_admin() -> str:
        return "nope"

    assert mcp._gate_tool_catalog.search("hidden_admin")["total"] == 0
    load_tool_config.cache_clear()
