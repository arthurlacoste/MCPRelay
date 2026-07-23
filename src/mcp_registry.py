from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Mapping

from fastmcp import Client, FastMCP
from fastmcp.mcp_config import MCPConfig
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import StatefulProxyClient
from fastmcp.server.transforms import ToolTransform
from fastmcp.tools.tool_transform import ToolTransformConfig

from command_guard import GuardService
from mcp_proxy import (
    ProxyCallLoggingMiddleware,
    ProxyCommandGuardMiddleware,
    ProxyServerConfig,
    load_proxy_config,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class RegistryDiff:
    added_servers: set[str] = field(default_factory=set)
    removed_servers: set[str] = field(default_factory=set)
    changed_servers: set[str] = field(default_factory=set)
    added_tools: set[str] = field(default_factory=set)
    removed_tools: set[str] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return any(asdict(self).values())

    def as_dict(self) -> dict[str, list[str]]:
        return {key: sorted(value) for key, value in asdict(self).items()}


@dataclass
class ServerState:
    name: str
    prefix: str
    status: str
    transport: str
    tool_count: int = 0
    last_refresh_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    retry_count: int = 0
    next_retry_at: datetime | None = None
    config_fingerprint: str = ""
    catalog_fingerprint: str = ""
    public_tools: set[str] = field(default_factory=set, repr=False)
    config: ProxyServerConfig | None = field(default=None, repr=False)
    client: Client | None = field(default=None, repr=False)
    provider: Any = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "prefix": self.prefix,
            "status": self.status,
            "transport": self.transport,
            "tool_count": self.tool_count,
            "last_refresh_at": _iso(self.last_refresh_at),
            "last_success_at": _iso(self.last_success_at),
            "last_error": self.last_error,
            "retry_count": self.retry_count,
            "next_retry_at": _iso(self.next_retry_at),
        }


class MCPRegistry:
    def __init__(
        self,
        config_path: str | Path,
        *,
        project_root: str | Path,
        environ: Mapping[str, str] | None = None,
        event_logger: Callable[[str, dict[str, Any]], None] | None = None,
        command_guard: GuardService | None = None,
        refresh_interval_seconds: float | None = None,
        retry_initial_seconds: float | None = None,
        retry_max_seconds: float | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        candidate = Path(config_path)
        self.config_path = candidate if candidate.is_absolute() else self.project_root / candidate
        self.environ = os.environ if environ is None else environ
        self.event_logger = event_logger
        self.command_guard = command_guard
        self.refresh_interval_seconds = float(
            refresh_interval_seconds if refresh_interval_seconds is not None
            else self.environ.get("MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS", 60)
        )
        self.retry_initial_seconds = float(
            retry_initial_seconds if retry_initial_seconds is not None
            else self.environ.get("MCP_DISCOVERY_RETRY_INITIAL_SECONDS", 2)
        )
        self.retry_max_seconds = float(
            retry_max_seconds if retry_max_seconds is not None
            else self.environ.get("MCP_DISCOVERY_RETRY_MAX_SECONDS", 300)
        )
        self.gateway: FastMCP | None = None
        self.states: dict[str, ServerState] = {}
        self._native_tools: set[str] = set()
        self._lock = asyncio.Lock()
        self._watch_task: asyncio.Task | None = None
        self._closed = False

    def _event(self, action: str, payload: dict[str, Any]) -> None:
        logger.info("%s %s", action, payload.get("server", ""))
        if self.event_logger:
            self.event_logger(action, payload)

    async def start(self, gateway: FastMCP) -> None:
        self.gateway = gateway
        self._native_tools = {tool.name for tool in await gateway.list_tools()}
        await self.refresh()
        if self.refresh_interval_seconds > 0:
            self._watch_task = asyncio.create_task(self._watch(), name="mcp-registry-watch")

    async def _watch(self) -> None:
        while not self._closed:
            try:
                await asyncio.sleep(self.refresh_interval_seconds)
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("MCP registry background refresh failed")

    def _server_fingerprint(self, server: ProxyServerConfig) -> str:
        return _fingerprint({
            "name": server.name,
            "prefix": server.prefix,
            "config": server.config,
            "init_timeout": server.init_timeout,
            "call_timeout": server.call_timeout,
        })

    async def _load_configured(self) -> dict[str, ProxyServerConfig]:
        servers = await asyncio.to_thread(
            load_proxy_config,
            self.config_path,
            project_root=self.project_root,
            environ=self.environ,
        )
        return {server.name: server for server in servers}

    async def refresh(self) -> RegistryDiff:
        configured = await self._load_configured()
        async with self._lock:
            return await self._refresh_locked(configured)

    async def _refresh_locked(self, configured: dict[str, ProxyServerConfig]) -> RegistryDiff:
        diff = RegistryDiff()
        for name in list(self.states):
            if name not in configured:
                old = self.states[name]
                diff.removed_servers.add(name)
                diff.removed_tools.update(old.public_tools)
                await self._remove_locked(name)

        now = _utcnow()
        for name, server in configured.items():
            state = self.states.get(name)
            fingerprint = self._server_fingerprint(server)
            should_retry = state is not None and state.status in {"offline", "degraded"} and (
                state.next_retry_at is None or state.next_retry_at <= now
            )
            if state is None:
                diff.added_servers.add(name)
                await self._reload_locked(server, diff)
            elif state.config_fingerprint != fingerprint:
                diff.changed_servers.add(name)
                await self._reload_locked(server, diff)
            elif should_retry:
                await self._reload_locked(server, diff)
        if diff.changed:
            self._event("mcp_catalog_changed", diff.as_dict())
        return diff

    async def reload_server(self, server_name: str) -> ServerState:
        configured = await self._load_configured()
        async with self._lock:
            if server_name not in configured:
                raise KeyError(f"unknown or disabled MCP server: {server_name}")
            diff = RegistryDiff(changed_servers={server_name})
            await self._reload_locked(configured[server_name], diff)
            if diff.changed:
                self._event("mcp_catalog_changed", diff.as_dict())
            return self.states[server_name]

    async def _reload_locked(self, server: ProxyServerConfig, diff: RegistryDiff) -> None:
        if self.gateway is None:
            raise RuntimeError("registry has not started")
        old = self.states.get(server.name)
        self._event("mcp_server_reload_started", {"server": server.name, "prefix": server.prefix})
        started = monotonic()
        client: Client | None = None
        try:
            if not server.prefix or any(
                state.prefix == server.prefix for name, state in self.states.items() if name != server.name
            ):
                logger.error("MCP server %r omitted: namespace collision for %r", server.name, server.prefix)
                raise ValueError(f"namespace collision for {server.prefix!r}")
            config = dict(server.config)
            raw_transforms = config.pop("tools", {})
            guard_mappings = {
                "run_command": {"commandArgument": "command", "cwdArgument": "cwd"},
                "filesystem_execute_tool": {"commandArgument": "command", "cwdArgument": "cwd"},
                **config.pop("commandGuards", {}),
            }
            parsed = MCPConfig.from_dict({"mcpServers": {server.name: config}})
            transport_config = parsed.mcpServers[server.name]
            transport = transport_config.to_transport()
            if hasattr(transport, "forward_incoming_headers"):
                transport.forward_incoming_headers = False
            client = StatefulProxyClient(transport, timeout=server.call_timeout, init_timeout=server.init_timeout)
            await client.__aenter__()
            tools = await client.list_tools()
            # FastMCP providers resolve resources and prompts dynamically. Avoid
            # probing optional capabilities here because older servers may not
            # answer unsupported list methods.
            transforms = {name: ToolTransformConfig.model_validate(value) for name, value in raw_transforms.items()}
            public_tools = {
                f"{server.prefix}_{transforms[t.name].name or t.name}" if t.name in transforms else f"{server.prefix}_{t.name}"
                for t in tools if t.name not in transforms or transforms[t.name].enabled
            }
            occupied = set(self._native_tools)
            for name, state in self.states.items():
                if name != server.name and state.provider is not None:
                    occupied.update(state.public_tools)
            collisions = public_tools & occupied
            if collisions:
                raise ValueError(f"tool name collision: {', '.join(sorted(collisions))}")

            proxy = create_proxy(client, name=server.name)
            if transforms:
                proxy.add_transform(ToolTransform(transforms))
            if guard_mappings and self.command_guard:
                proxy.add_middleware(ProxyCommandGuardMiddleware(server.name, guard_mappings, self.command_guard))
            if self.event_logger:
                proxy.add_middleware(ProxyCallLoggingMiddleware(server.name, self.event_logger))

            before = len(self.gateway.providers)
            self.gateway.add_provider(proxy, namespace=server.prefix)
            provider = self.gateway.providers[before]
            state = ServerState(
                name=server.name,
                prefix=server.prefix,
                status="healthy",
                transport="stdio" if "command" in config else "http",
                tool_count=len(public_tools),
                last_refresh_at=_utcnow(),
                last_success_at=_utcnow(),
                config_fingerprint=self._server_fingerprint(server),
                catalog_fingerprint=_fingerprint(sorted(public_tools)),
                public_tools=public_tools,
                config=server,
                client=client,
                provider=provider,
            )
            self.states[server.name] = state
            if old and old.provider in self.gateway.providers:
                self.gateway.providers.remove(old.provider)
            if old and old.client:
                with suppress(Exception, asyncio.CancelledError):
                    await old.client.close()
            if old:
                diff.added_tools.update(public_tools - old.public_tools)
                diff.removed_tools.update(old.public_tools - public_tools)
            else:
                diff.added_tools.update(public_tools)
            self._event("mcp_server_reload_succeeded", {
                "server": server.name, "prefix": server.prefix, "status": "healthy",
                "tool_count": len(public_tools), "duration_ms": round((monotonic()-started)*1000, 2),
            })
        except Exception as exc:
            if client:
                with suppress(Exception, asyncio.CancelledError):
                    await client.close()
            retry_count = (old.retry_count if old else 0) + 1
            delay = min(self.retry_initial_seconds * (2 ** (retry_count - 1)), self.retry_max_seconds)
            if old and old.provider is not None:
                old.last_refresh_at = _utcnow()
                old.last_error = type(exc).__name__
                old.retry_count = retry_count
                old.next_retry_at = _utcnow() + timedelta(seconds=delay)
                old.status = "degraded"
                old.config = server
                old.config_fingerprint = self._server_fingerprint(server)
            else:
                self.states[server.name] = ServerState(
                    name=server.name, prefix=server.prefix, status="offline",
                    transport="stdio" if "command" in server.config else "http",
                    last_refresh_at=_utcnow(), last_error=type(exc).__name__, retry_count=retry_count,
                    next_retry_at=_utcnow() + timedelta(seconds=delay),
                    config_fingerprint=self._server_fingerprint(server), config=server,
                )
            logger.error("MCP server %r reload failed: %s", server.name, type(exc).__name__)
            self._event("mcp_server_reload_failed", {
                "server": server.name, "prefix": server.prefix, "status": self.states[server.name].status,
                "error_type": type(exc).__name__, "duration_ms": round((monotonic()-started)*1000, 2),
            })

    async def remove_server(self, server_name: str) -> None:
        async with self._lock:
            await self._remove_locked(server_name)

    async def _remove_locked(self, server_name: str) -> None:
        state = self.states.pop(server_name, None)
        if not state:
            return
        if self.gateway and state.provider in self.gateway.providers:
            self.gateway.providers.remove(state.provider)
        if state.client:
            with suppress(Exception, asyncio.CancelledError):
                await state.client.close()
        self._event("mcp_server_disconnected", {"server": state.name, "prefix": state.prefix})

    def list_servers(self) -> list[dict[str, Any]]:
        return [self.states[name].as_dict() for name in sorted(self.states)]

    def server_status(self, server_name: str) -> dict[str, Any] | None:
        state = self.states.get(server_name)
        return state.as_dict() if state else None

    async def close(self) -> None:
        self._closed = True
        if self._watch_task:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
        async with self._lock:
            for name in list(self.states):
                await self._remove_locked(name)
