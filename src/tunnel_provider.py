"""Tunnel provider selection and process commands for Gate launchers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_PROVIDERS = {"ngrok", "tailscale", "external"}
HTTPS_URL_RE = re.compile(r"https://[^\s\"']+")


class TunnelConfigurationError(RuntimeError):
    """Raised when a tunnel provider cannot be used."""


@dataclass(frozen=True)
class TunnelSpec:
    provider: str
    command: list[str] | None
    log_path: Path | None
    display_name: str


def normalize_provider(value: str | None) -> str:
    provider = (value or "ngrok").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise TunnelConfigurationError(
            f"Unsupported TUNNEL_PROVIDER={provider!r}. Supported values: {supported}."
        )
    return provider


def require_cli(provider: str, which=shutil.which) -> str:
    if provider == "external":
        return ""
    executable = which(provider)
    if executable:
        return executable
    if provider == "tailscale":
        raise TunnelConfigurationError(
            "Tailscale CLI was not found. Install Tailscale, run 'tailscale up', then retry."
        )
    raise TunnelConfigurationError(
        "ngrok was not found. Install ngrok and configure its authtoken, then retry."
    )


def validate_tailscale_session(run=subprocess.run) -> None:
    result = run(
        ["tailscale", "status", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise TunnelConfigurationError(
            "Tailscale is not authenticated. Run 'tailscale up' and retry."
        )
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise TunnelConfigurationError("Could not read Tailscale session status.") from exc
    if payload.get("BackendState") != "Running":
        raise TunnelConfigurationError(
            "Tailscale is not running. Run 'tailscale up' and retry."
        )


def parse_tailscale_https_url(output: str) -> str:
    for url in HTTPS_URL_RE.findall(output):
        cleaned = url.rstrip("/.,;)")
        if cleaned.startswith("https://"):
            return cleaned
    return ""


def tailscale_public_url(run=subprocess.run) -> str:
    result = run(
        ["tailscale", "funnel", "status", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    url = parse_tailscale_https_url(combined)
    if result.returncode == 0 and url:
        return url
    raise TunnelConfigurationError(
        "Could not detect a public Tailscale Funnel HTTPS URL. "
        "Run 'tailscale funnel 8761' once and confirm Funnel is allowed for this tailnet."
    )


def build_tunnel_spec(provider: str, port: int, log_root: Path) -> TunnelSpec:
    provider = normalize_provider(provider)
    if provider == "external":
        return TunnelSpec(provider, None, None, "external tunnel")
    require_cli(provider)
    if provider == "tailscale":
        validate_tailscale_session()
        return TunnelSpec(
            provider,
            ["tailscale", "funnel", "--bg=false", str(port)],
            log_root / "tailscale.log",
            "Tailscale Funnel",
        )
    return TunnelSpec(
        provider,
        ["ngrok", "http", str(port), "--log=stdout"],
        log_root / "ngrok.log",
        "ngrok",
    )
