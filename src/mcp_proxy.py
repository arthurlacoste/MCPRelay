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


VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
logger = logging.getLogger(__name__)


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
) -> list[ProxyServerConfig]:
    root = Path(project_root)
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("MCP proxy config not found: %s", config_path)
        return []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(
            "MCP proxy config could not be loaded from %s: %s",
            config_path,
            type(exc).__name__,
        )
        return []
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers"), dict):
        logger.error("MCP proxy config %s must contain an mcpServers object", config_path)
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
    def __init__(
        self,
        config_path: str | Path,
        *,
        project_root: str | Path,
        environ: Mapping[str, str] | None = None,
        event_logger: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        candidate = Path(config_path)
        self.config_path = (
            candidate if candidate.is_absolute() else self.project_root / candidate
        )
        self.environ = os.environ if environ is None else environ
        self.event_logger = event_logger
        self._clients: list[Client] = []

    async def start(self, gateway: FastMCP) -> None:
        existing_names = {tool.name for tool in await gateway.list_tools()}
        prefixes: set[str] = set()
        for server in load_proxy_config(
            self.config_path,
            project_root=self.project_root,
            environ=self.environ,
        ):
            if not server.prefix or server.prefix in prefixes:
                logger.error(
                    "MCP server %r omitted: namespace collision for %r",
                    server.name,
                    server.prefix,
                )
                continue

            config = dict(server.config)
            raw_transforms = config.pop("tools", {})
            client: Client | None = None
            try:
                parsed = MCPConfig.from_dict({"mcpServers": {server.name: config}})
                transport = parsed.mcpServers[server.name].to_transport()
                client = StatefulProxyClient(
                    transport,
                    timeout=server.call_timeout,
                    init_timeout=server.init_timeout,
                )
                await client.__aenter__()
                tools = await client.list_tools()

                transforms = {
                    name: ToolTransformConfig.model_validate(value)
                    for name, value in raw_transforms.items()
                }
                public_names = {
                    f"{server.prefix}_{transforms[tool.name].name or tool.name}"
                    if tool.name in transforms
                    else f"{server.prefix}_{tool.name}"
                    for tool in tools
                    if tool.name not in transforms or transforms[tool.name].enabled
                }
                collisions = public_names & existing_names
                if collisions:
                    with suppress(Exception, asyncio.CancelledError):
                        await client.close()
                    logger.error(
                        "MCP server %r omitted: tool name collision: %s",
                        server.name,
                        ", ".join(sorted(collisions)),
                    )
                    continue

                proxy = create_proxy(client, name=server.name)
                if hasattr(transport, "forward_incoming_headers"):
                    transport.forward_incoming_headers = False
                if transforms:
                    proxy.add_transform(ToolTransform(transforms))
                if self.event_logger is not None:
                    proxy.add_middleware(
                        ProxyCallLoggingMiddleware(server.name, self.event_logger)
                    )
                gateway.mount(proxy, namespace=server.prefix)
            except Exception as exc:
                if client is not None:
                    with suppress(Exception, asyncio.CancelledError):
                        await client.close()
                logger.error("MCP server %r omitted: %s", server.name, type(exc).__name__)
                continue

            prefixes.add(server.prefix)
            existing_names.update(public_names)
            assert client is not None
            self._clients.append(client)
            logger.info("MCP server %r mounted as %r", server.name, server.prefix)

    async def close(self) -> None:
        while self._clients:
            client = self._clients.pop()
            try:
                await client.close()
            except Exception:
                logger.exception("Failed to close MCP proxy client")
