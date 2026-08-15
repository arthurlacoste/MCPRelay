from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Mapping

from fastmcp import Client, FastMCP
from fastmcp.mcp_config import MCPConfig
from fastmcp.server import create_proxy
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers.proxy import StatefulProxyClient
from fastmcp.server.transforms import ToolTransform
from fastmcp.tools.tool_transform import ToolTransformConfig
from command_guard import GuardService, current_guard_request


VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
logger = logging.getLogger(__name__)


class ProxyCommandGuardMiddleware(Middleware):
    def __init__(self, server_name: str, mappings: Mapping[str, Mapping[str, str]], guard: GuardService) -> None:
        self.server_name = server_name
        self.mappings = mappings
        self.guard = guard

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        mapping = self.mappings.get(context.message.name)
        if mapping:
            arguments = context.message.arguments or {}
            command = arguments.get(mapping.get("commandArgument", "command"))
            cwd = arguments.get(mapping.get("cwdArgument", "cwd"))
            if not isinstance(command, str):
                raise ValueError("configured guarded proxy tool requires a string command argument")
            result = self.guard.inspect(current_guard_request(
                f"{self.server_name}_{context.message.name}", arguments, command, cwd,
                mapping.get("host"),
            ))
            if result.decision == "deny":
                raise PermissionError(json.dumps({"status": "denied", **result.as_dict()}))
        return await call_next(context)


class ProxyCallLoggingMiddleware(Middleware):
    def __init__(
        self,
        server_name: str,
        event_logger: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.server_name = server_name
        self.event_logger = event_logger

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        started = monotonic()
        payload = {
            "server": self.server_name,
            "tool": context.message.name,
        }
        try:
            result = await call_next(context)
        except Exception:
            payload["status"] = "error"
            payload["duration_ms"] = round((monotonic() - started) * 1000, 2)
            self.event_logger("mcp_proxy_call", payload)
            raise
        payload["status"] = "success"
        payload["duration_ms"] = round((monotonic() - started) * 1000, 2)
        self.event_logger("mcp_proxy_call", payload)
        return result


class ProxyConfigUnavailable(RuntimeError):
    """Raised when the registry file cannot be trusted for reconciliation."""


@dataclass(frozen=True)
class ProxyServerConfig:
    name: str
    prefix: str
    config: dict[str, Any]
    init_timeout: float = 10.0
    call_timeout: float | None = None


def _expand(value: Any, environ: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return VARIABLE.sub(lambda match: environ[match.group(1)], value)
    if isinstance(value, list):
        return [_expand(item, environ) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, environ) for key, item in value.items()}
    return value


def _normalize_prefix(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", name)
    return re.sub(r"_+", "_", normalized).strip("_").lower()


def load_proxy_config(
    path: str | Path,
    *,
    project_root: str | Path,
    environ: Mapping[str, str],
    raise_on_error: bool = False,
) -> list[ProxyServerConfig]:
    """Load enabled MCP proxy servers from a classic ``mcpServers`` file.

    By default, unavailable or structurally invalid registry files are logged
    and treated as empty for backward compatibility. Registry reconciliation
    passes ``raise_on_error=True`` so it can preserve the last healthy catalog
    instead of interpreting a failed read as an explicit request to remove all
    servers. Per-server validation failures remain isolated and are omitted.
    """
    root = Path(project_root)
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        logger.warning("MCP proxy config not found: %s", config_path)
        if raise_on_error:
            raise ProxyConfigUnavailable(f"registry file not found: {config_path}") from exc
        return []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(
            "MCP proxy config could not be loaded from %s: %s",
            config_path,
            type(exc).__name__,
        )
        if raise_on_error:
            raise ProxyConfigUnavailable(f"{type(exc).__name__} reading {config_path}") from exc
        return []
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        logger.error("MCP proxy config %s must contain an mcpServers object", config_path)
        if raise_on_error:
            raise ProxyConfigUnavailable(f"missing mcpServers object in {config_path}")
        return []
    servers = []
    for name, raw_config in data["mcpServers"].items():
        if not isinstance(raw_config, dict):
            logger.error("MCP server %r omitted: configuration must be an object", name)
            continue
        if raw_config.get("enabled", True) is False:
            continue
        try:
            config = _expand(raw_config, environ)
        except KeyError as exc:
            logger.error(
                "MCP server %r omitted: environment variable %s is missing",
                name,
                exc.args[0],
            )
            continue
        cwd = config.get("cwd")
        if cwd and not Path(cwd).is_absolute():
            config["cwd"] = str(root / cwd)
        prefix_source = config.pop("toolPrefix", name)
        init_timeout = float(config.pop("initTimeoutMs", 10_000)) / 1000
        timeout = config.pop("timeout", None)
        config.pop("enabled", None)
        servers.append(
            ProxyServerConfig(
                name=name,
                prefix=_normalize_prefix(prefix_source),
                config=config,
                init_timeout=init_timeout,
                call_timeout=float(timeout) / 1000 if timeout is not None else None,
            )
        )
    return servers


class MCPProxyManager:
    """Compatibility facade around the hot-reload registry."""

    def __init__(self, config_path: str | Path, **options: Any) -> None:
        from mcp_registry import MCPRegistry

        self.registry = MCPRegistry(config_path, **options)

    async def start(self, gateway: FastMCP) -> None:
        await self.registry.start(gateway)

    async def refresh(self):
        return await self.registry.refresh()

    def request_refresh(self):
        return self.registry.request_refresh()

    async def reload_server(self, server_name: str):
        return await self.registry.reload_server(server_name)

    async def remove_server(self, server_name: str) -> None:
        await self.registry.remove_server(server_name)

    def search_tools(self, query: str | None = None, *, server_name: str | None = None, limit: int = 8, offset: int = 0):
        return self.registry.search_tools(query, server_name=server_name, limit=limit, offset=offset)

    def read_tool(self, server_name: str, tool_name: str):
        return self.registry.read_tool(server_name, tool_name)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None):
        return await self.registry.call_tool(server_name, tool_name, arguments)

    def list_servers(self) -> list[dict[str, Any]]:
        return self.registry.list_servers()

    def server_status(self, server_name: str) -> dict[str, Any] | None:
        return self.registry.server_status(server_name)

    async def close(self) -> None:
        await self.registry.close()
