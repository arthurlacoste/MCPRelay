from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_gateway_environment(base_dir: Path) -> bool:
    """Load the gateway's config/.env without overriding process variables."""
    return load_dotenv(base_dir / 'config' / '.env')
