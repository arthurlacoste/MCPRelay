from __future__ import annotations

import logging
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = BASE_DIR / 'config' / 'tools.toml'
TOOL_EXPOSURE_MODES = ('discover', 'full')
logger = logging.getLogger(__name__)
DISCOVER_CORE_TOOLS = frozenset({
    'run_command',
    'skills_search',
    'skills_read',
    'mcp_servers_list',
    'mcp_tools_search',
    'mcp_tool_read',
    'mcp_tool_call',
    # Only registered when the optional command queue is enabled.
    'get_queue_state',
    'get_command_state',
    'stop_command',
    'get_command_output',
    'get_command_log',
    'resolve_command_recovery',
})


def normalize_tool_exposure_mode(value: str | None, *, source: str = 'MCP_TOOL_EXPOSURE_MODE') -> str:
    mode = (value or 'discover').strip().lower()
    if mode not in TOOL_EXPOSURE_MODES:
        logger.warning("Invalid %s=%r; falling back to 'discover'", source, value)
        return 'discover'
    return mode


def tool_exposure_mode(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return normalize_tool_exposure_mode(env.get('MCP_TOOL_EXPOSURE_MODE'))


def is_tool_exposed(name: str, environ: dict[str, str] | None = None) -> bool:
    return tool_exposure_mode(environ) == 'full' or name in DISCOVER_CORE_TOOLS


@lru_cache(maxsize=1)
def load_tool_config(path: str | None = None) -> dict[str, Any]:
    config_path = Path(path or os.getenv('MCP_TOOLS_CONFIG', DEFAULT_CONFIG))
    if not config_path.is_file():
        return {}
    with config_path.open('rb') as handle:
        return tomllib.load(handle)


def is_tool_enabled(name: str, config: dict[str, Any] | None = None) -> bool:
    cfg = config if config is not None else load_tool_config()
    return bool(cfg.get('tools', {}).get(name, True))


def configurable_tool(mcp, name: str | None = None, **tool_options: Any) -> Callable:
    def decorator(func):
        tool_name = name or func.__name__
        if not is_tool_enabled(tool_name) or not is_tool_exposed(tool_name):
            return func
        options = {'name': name, **tool_options} if name else tool_options
        return mcp.tool(**options)(func)
    return decorator
