from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = BASE_DIR / 'config' / 'tools.toml'


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


def is_downstream_enabled(namespace: str, name: str, config: dict[str, Any] | None = None) -> bool:
    cfg = config if config is not None else load_tool_config()
    downstream = cfg.get('downstream_mcp', {}).get(namespace, {})
    if downstream.get('enabled', True) is False:
        return False
    return bool(downstream.get('tools', {}).get(name, True))


def configurable_tool(mcp, name: str | None = None) -> Callable:
    def decorator(func):
        tool_name = name or func.__name__
        if not is_tool_enabled(tool_name):
            return func
        return mcp.tool(name=name)(func) if name else mcp.tool()(func)
    return decorator
