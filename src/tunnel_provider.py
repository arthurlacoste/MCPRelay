"""Tunnel provider selection and process commands for Gate launchers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_PROVIDERS = {"ngrok", "tailscale", "cloudflare", "external"}
HTTPS_URL_RE = re.compile(r"https://[^\s\"']+")
CLOUDFLARED_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
TAILSCALE_COMMAND_TIMEOUT_SECONDS = 10


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


def require_cli(provider: str, which=None) -> str:
    if provider == "external":
        return ""
    resolver = which or shutil.which
    executable = resolver({"cloudflare": "cloudflared"}.get(provider, provider))
    if executable:
        return executable
    if provider == "tailscale":
        raise TunnelConfigurationError(
            "Tailscale CLI was not found. Install Tailscale, run 'tailscale up', then retry."
        )
    if provider == "cloudflare":
        raise TunnelConfigurationError(
            "cloudflared was not found. Install it (macOS: 'brew install cloudflared', "
            "Linux: 'curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/"
            "cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared', "
            "Windows: 'winget install --id Cloudflare.cloudflared'), then retry."
        )
    raise TunnelConfigurationError(
        "ngrok was not found. Install ngrok and configure its authtoken, then retry."
    )


def validate_tailscale_session(run=subprocess.run) -> None:
    try:
        result = run(
            ["tailscale", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=TAILSCALE_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TunnelConfigurationError("Tailscale status timed out. Check that the Tailscale daemon is running.") from exc
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


def parse_cloudflared_url(output: str) -> str:
    match = CLOUDFLARED_URL_RE.search(output)
    return match.group(0).rstrip("/.,;)") if match else ""


def cloudflared_public_url(log_path: Path | str, read_log=None) -> str:
    reader = read_log or (lambda path: Path(path).read_text(encoding="utf-8", errors="replace"))
    try:
        text = reader(log_path)
    except OSError:
        return ""
    return parse_cloudflared_url(text)


def cloudflared_registered(log_path: Path | str, read_log=None) -> bool:
    reader = read_log or (lambda path: Path(path).read_text(encoding="utf-8", errors="replace"))
    try:
        text = reader(log_path)
    except OSError:
        return False
    return "Registered tunnel connection" in text


def _tailscale_json_funnel_url(payload: dict, port: int | None = None) -> str:
    """Funnel HTTPS URL from `tailscale funnel status --json` output.

    The JSON carries the served hostname as a Web key ("<machine>.ts.net:443")
    and, for foreground funnels, the proxy target. When `port` is given, only a
    funnel that proxies to that local port is accepted, so a Funnel pointing at
    another service is never mistaken for Gate's.
    """
    for section in ("Foreground", "serve"):
        for entry in (payload.get(section) or {}).values():
            for key, handler in (entry.get("Web") or {}).items():
                host = key.split(":", 1)[0]
                if not host:
                    continue
                if port is not None:
                    proxy = ""
                    for nested in (handler or {}).get("Handlers") or {}:
                        proxy = (handler["Handlers"][nested] or {}).get("Proxy") or ""
                        if proxy:
                            break
                    if not proxy.endswith(f":{port}"):
                        continue
                return f"https://{host}"
    return ""


def tailscale_public_url(run=subprocess.run, port: int | None = None) -> str:
    try:
        result = run(
            ["tailscale", "funnel", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=TAILSCALE_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise TunnelConfigurationError("Tailscale Funnel status timed out.") from exc
    combined = f"{result.stdout}\n{result.stderr}"
    url = parse_tailscale_https_url(combined)
    if result.returncode == 0 and url:
        return url
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        url = _tailscale_json_funnel_url(payload, port=port)
        if url:
            return url
    raise TunnelConfigurationError(
        "Could not detect a public Tailscale Funnel HTTPS URL. "
        "Run 'tailscale funnel 8761' once and confirm Funnel is allowed for this tailnet."
    )


def build_tunnel_spec(
    provider: str,
    port: int,
    log_root: Path,
    *,
    ngrok_target: str | None = None,
    cloudflared_tunnel_name: str | None = None,
) -> TunnelSpec:
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
    if provider == "cloudflare":
        if cloudflared_tunnel_name:
            command = [
                "cloudflared",
                "tunnel",
                "--no-autoupdate",
                "run",
                "--url",
                f"http://127.0.0.1:{port}",
                cloudflared_tunnel_name,
            ]
            display_name = f"Cloudflare Tunnel ({cloudflared_tunnel_name})"
        else:
            command = ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"]
            display_name = "Cloudflare Tunnel"
        return TunnelSpec(provider, command, log_root / "cloudflared.log", display_name)
    return TunnelSpec(
        provider,
        ["ngrok", "http", ngrok_target or str(port), "--log=stdout"],
        log_root / "ngrok.log",
        "ngrok",
    )
