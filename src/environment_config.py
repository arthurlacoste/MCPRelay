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


def load_gateway_environment(base_dir: Path) -> bool:
    """Load Gate's config/.env without overriding process variables."""
    return load_dotenv(gateway_paths(base_dir).config / ".env")
