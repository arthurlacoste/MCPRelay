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
