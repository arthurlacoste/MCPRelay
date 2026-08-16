"""One-shot Cloudflare connect tunnel setup for Gate."""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .config import read_env

DEFAULT_TUNNEL_NAME = "gate"
SUPPORTED_PROVIDERS = {"cf", "cloudflare"}
FOREIGN_HOSTNAME_HINTS = (
    "ngrok-free.dev",
    "ngrok.app",
    "ngrok.io",
    "trycloudflare.com",
    "localtunnel.me",
    "serveo.net",
    ".ts.net",
    "nip.io",
)


def is_foreign_provider_hostname(hostname: str) -> bool:
    lower = hostname.lower()
    return any(hint in lower for hint in FOREIGN_HOSTNAME_HINTS)


def derive_connect_hostname(current_base_url: str) -> str | None:
    hostname = normalize_hostname(current_base_url)
    if not hostname or is_foreign_provider_hostname(hostname):
        return None
    return hostname


def cloudflare_zone(cert_file: Path | None = None) -> str:
    """Best-effort zone name from ~/.cloudflared/cert.pem (empty string when unknown)."""
    cert_file = cert_file or Path.home() / ".cloudflared" / "cert.pem"
    if not cert_file.exists():
        return ""
    try:
        raw = cert_file.read_bytes()
        token = raw.split(b"-----BEGIN ARGO TUNNEL TOKEN-----")[1].split(b"-----END ARGO TUNNEL TOKEN-----")[0]
        token += b"=" * (-len(token) % 4)
        data = json.loads(base64.urlsafe_b64decode(token))
        zone_id = data["zoneID"]
        api_token = data["apiToken"]
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(request, timeout=6) as response:
            body = json.load(response)
        result = body.get("result") or {}
        return (result.get("name") or "").strip() if body.get("success") else ""
    except Exception:
        return ""


def project_dir() -> Path:
    configured = os.environ.get("GATE_PROJECT_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def project_config_file() -> Path:
    configured = os.environ.get("MCP_CONFIG_ROOT")
    root = Path(configured) if configured else project_dir() / "config"
    return root / ".env"


def cloudflared_executable() -> str | None:
    return shutil.which("cloudflared")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=False, **kwargs)


def install_cloudflared() -> bool:
    system = platform.system()
    if system == "Darwin":
        return _run(["brew", "install", "cloudflared"]).returncode == 0
    if system == "Windows":
        return _run(["winget", "install", "--id", "Cloudflare.cloudflared"]).returncode == 0
    script = (
        "curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/"
        "cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"
    )
    return _run(["sh", "-c", script]).returncode == 0


def cloudflared_logged_in() -> bool:
    return _run(["cloudflared", "tunnel", "list"], capture_output=True).returncode == 0


def tunnel_exists(name: str) -> bool:
    result = _run(["cloudflared", "tunnel", "list"], capture_output=True, text=True)
    return result.returncode == 0 and name in (result.stdout or "")


def cloudflared_login() -> bool:
    return _run(["cloudflared", "tunnel", "login"]).returncode == 0


def create_tunnel(name: str) -> bool:
    return _run(["cloudflared", "tunnel", "create", name]).returncode == 0


def route_dns(name: str, hostname: str) -> bool:
    return _run(["cloudflared", "tunnel", "route", "dns", name, hostname]).returncode == 0


def write_env(path: Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    kept = [
        line
        for line in lines
        if not (
            line
            and not line.lstrip().startswith("#")
            and "=" in line
            and line.split("=", 1)[0].strip() in updates
        )
    ]
    kept.append("")
    for key, value in updates.items():
        kept.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def normalize_hostname(value: str) -> str:
    return value.split("://", 1)[-1].split("/", 1)[0].strip()


def command_connect(
    provider: str,
    tunnel_name: str | None = None,
    hostname: str | None = None,
    *,
    yes: bool = False,
    input_func=input,
) -> int:
    if provider not in SUPPORTED_PROVIDERS:
        print(f"Unsupported provider: {provider!r}. Use 'cf' (Cloudflare).")
        return 1
    env_file = project_config_file()
    print("Configuring Cloudflare connect tunnel...")
    current_provider = read_env(env_file).get("TUNNEL_PROVIDER", "")
    if current_provider and current_provider not in ("cloudflare", "cf"):
        print(f"ℹ Switching tunnel provider from {current_provider} to cloudflare.")

    if cloudflared_executable() is None:
        if not yes:
            answer = input_func("cloudflared is not installed. Install it now? [Y/n] ").strip().lower()
            if answer not in {"", "y", "yes"}:
                print("Aborted. Install cloudflared first, then retry.")
                return 1
        print("Installing cloudflared...")
        if not install_cloudflared():
            print("cloudflared installation failed.")
            return 1
        if cloudflared_executable() is None:
            print("cloudflared still not found after install. Check PATH and retry.")
            return 1

    if not cloudflared_logged_in():
        print("Logging in to Cloudflare (a browser window will open)...")
        if not cloudflared_login():
            print("Cloudflare login failed. Run 'cloudflared tunnel login' manually, then retry.")
            return 1

    name = tunnel_name or DEFAULT_TUNNEL_NAME
    if not tunnel_exists(name):
        print(f"Creating Cloudflare tunnel '{name}'...")
        if not create_tunnel(name):
            print(f"Could not create Cloudflare tunnel '{name}'.")
            return 1

    if not hostname:
        configured = read_env(env_file).get("MCP_BASE_URL", "")
        derived = derive_connect_hostname(configured) if configured else None
        zone = ""
        if configured and derived is None:
            print(f"ℹ {configured} belongs to another tunnel provider; it will not be reused.")
            print("  Pick a fresh hostname on your Cloudflare domain (e.g. mcp.example.com).")
        if not derived:
            zone = cloudflare_zone()
            if zone:
                derived = f"mcp.{zone}"
        if derived:
            hostname = input_func(f"Public hostname [default {derived}]: ").strip() or derived
        else:
            hostname = input_func("Public hostname (e.g. mcp.example.com): ").strip()
    hostname = normalize_hostname(hostname)
    if hostname and "." not in hostname:
        zone = zone or cloudflare_zone()
        if zone:
            hostname = f"{hostname}.{zone}"
    if not hostname:
        print("A public hostname is required for a Cloudflare connect tunnel.")
        return 1

    print(f"Routing DNS for '{hostname}'...")
    if not route_dns(name, hostname):
        print(f"Could not route DNS for '{hostname}'. Confirm the domain is on your Cloudflare account.")
        return 1

    base_url = f"https://{hostname}"
    write_env(
        env_file,
        {
            "TUNNEL_PROVIDER": "cloudflare",
            "CLOUDFLARED_TUNNEL_NAME": name,
            "MCP_BASE_URL": base_url,
            "OAUTH_ISSUER": f"{base_url}/oauth",
            "LOCAL_OAUTH_ISSUER": f"{base_url}/oauth",
        },
    )
    print(f"✓ Cloudflare connect tunnel '{name}' ready at {base_url}")

    env = read_env(env_file)
    if not (env.get("OAUTH_ACCESS_SECRET") and env.get("OAUTH_ACCESS_SECRET_HASH", "").startswith("$argon2id$")):
        print("Run 'gate setup' to finish OAuth configuration.")
    return 0
