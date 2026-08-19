from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class GatewayPaths:
    config: Path
    data: Path
    logs: Path


def gateway_paths(base_dir: Path) -> GatewayPaths:
    return GatewayPaths(
        config=Path(os.environ.get("MCP_CONFIG_ROOT", base_dir / "config")),
        data=Path(os.environ.get("MCP_DATA_ROOT", base_dir / "data")),
        logs=Path(os.environ.get("MCP_LOG_ROOT", base_dir / "logs")),
    )


def mcp_servers_config_path(base_dir: Path) -> Path:
    raw = os.environ.get("MCP_SERVERS_CONFIG")
    if not raw:
        return gateway_paths(base_dir).config / "mcp.json"

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate

    # The documented/default value is config/mcp.json. In versioned installs,
    # BASE_DIR points at ~/.gate/current (a release symlink), while config is
    # persistent at ~/.gate/config. Keep config/... paths tied to that persistent
    # root so release switches cannot move the registry.
    if candidate.parts and candidate.parts[0] == "config":
        return gateway_paths(base_dir).config.joinpath(*candidate.parts[1:])

    # Preserve the historical meaning of other relative overrides.
    return base_dir / candidate


def load_gateway_environment(base_dir: Path) -> bool:
    """Load Gate's config/.env without overriding process variables."""
    loaded = load_dotenv(gateway_paths(base_dir).config / ".env")
    # Keep the externally visible MCP tool catalog stable unless an operator
    # explicitly opts into background subserver discovery. Some clients cache
    # discovered tool handles and cannot safely follow topology changes mid-run.
    os.environ.setdefault("MCP_DISCOVERY_REFRESH_INTERVAL_SECONDS", "0")
    return loaded
