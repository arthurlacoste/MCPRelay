"""One-shot tunnel provider setup for Gate.

- `gate connect ts` prepares Tailscale: installs the CLI when missing, logs in
  when needed, grants the non-root serve permission, and verifies Funnel.
- `gate connect cf` sets up a named Cloudflare tunnel on your own domain:
  installs `cloudflared`, logs in, creates the tunnel, routes DNS, and persists
  the configuration to `config/.env`.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

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

TAILSCALE_TIMEOUT_SECONDS = 10
TAILSCALE_DAEMON_START_TIMEOUT_SECONDS = 10
TAILSCALE_DAEMON_STATUS_TIMEOUT_SECONDS = 1
TAILSCALE_DAEMON_START_COMMAND_TIMEOUT_SECONDS = 30
TAILSCALE_DAEMON_RETRY_DELAY_SECONDS = 0.25
FUNNEL_ADMIN_URL = "https://login.tailscale.com/admin/dns"

Run = Callable[..., subprocess.CompletedProcess[str]]


# ── Cloudflare connect ───────────────────────────────────────────────────────


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


def _linux_cloudflared_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    if machine.startswith("armv"):
        return "armhf"
    return ""


def install_cloudflared() -> bool:
    system = platform.system()
    if system == "Darwin":
        return _run(["brew", "install", "cloudflared"]).returncode == 0
    if system == "Windows":
        return _run(["winget", "install", "--id", "Cloudflare.cloudflared"]).returncode == 0
    arch = _linux_cloudflared_arch()
    if not arch:
        print(f"Unsupported Linux architecture for automatic cloudflared installation: {platform.machine()}.")
        return False
    bin_dir = Path(os.environ.get("GATE_ROOT", str(Path.home() / ".gate"))) / "runtime" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    destination = bin_dir / "cloudflared"
    temporary = destination.with_suffix(".download")
    url = (
        "https://github.com/cloudflare/cloudflared/releases/latest/download/"
        f"cloudflared-linux-{arch}"
    )
    if _run(["curl", "-fsSL", url, "-o", str(temporary)]).returncode != 0:
        print("cloudflared download failed.")
        return False
    temporary.chmod(0o755)
    temporary.replace(destination)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return True


def cloudflared_logged_in() -> bool:
    return _run(["cloudflared", "tunnel", "list"], capture_output=True).returncode == 0


def tunnel_exists(name: str) -> bool:
    for args in (
        ["cloudflared", "tunnel", "list", "--name", name, "--output", "json"],
        ["cloudflared", "tunnel", "list", "--output", "json"],
    ):
        result = _run(args, capture_output=True, text=True)
        if result.returncode != 0:
            continue
        try:
            tunnels = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return False
        return any(str(item.get("name")) == name for item in tunnels)
    return False


def _warn_wrapped_login_url(stream=None) -> None:
    """cloudflared prints a ~150-char browser login URL that wraps on narrow
    terminals; a wrapped URL is easy to copy only in part."""
    stream = stream if stream is not None else sys.stdout
    if not stream.isatty():
        return
    width = shutil.get_terminal_size((80, 24)).columns
    if width >= 160:
        return
    stream.write(
        "\nThe login URL below is ONE long line and wraps across lines in this terminal.\n"
        "Copy the whole URL (both wrapped halves) into your browser.\n\n"
    )


def cloudflared_login() -> bool:
    _warn_wrapped_login_url()
    return _run(["cloudflared", "tunnel", "login"]).returncode == 0


def create_tunnel(name: str) -> bool:
    return _run(["cloudflared", "tunnel", "create", name]).returncode == 0


def route_dns(name: str, hostname: str) -> bool:
    result = _run(
        ["cloudflared", "tunnel", "route", "dns", name, hostname],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    combined = f"{result.stdout}\n{result.stderr}".lower()
    # Some cloudflared versions fail with a non-zero exit when the DNS record
    # already exists. For an idempotent re-run that is a success.
    if "already exists" in combined or "duplicate" in combined or "record exists" in combined:
        return True
    return False


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

    zone = ""
    if not hostname:
        configured = read_env(env_file).get("MCP_BASE_URL", "")
        derived = None
        if configured and current_provider in ("", "cloudflare", "cf"):
            derived = derive_connect_hostname(configured)
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


# ── Tailscale connect ────────────────────────────────────────────────────────


def current_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def _ask(prompt: str, default: bool = True, input_fn: Callable[[str], str] = input) -> bool:
    suffix = "Y/n" if default else "y/N"
    try:
        answer = input_fn(f"{prompt} [{suffix}] ").strip().lower()
    except EOFError:
        answer = ""
    if not answer:
        return default
    return answer in {"y", "yes"}


def tailscale_bin(which=shutil.which) -> str | None:
    return which("tailscale")


def platform_name() -> str:
    if sys.platform.startswith("darwin"):
        return "darwin"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def tailscale_install_script(platform: str | None = None) -> str:
    """Return the canonical one-liner to install the Tailscale CLI."""
    system = platform or platform_name()
    if system == "darwin":
        return "brew install tailscale"
    if system == "windows":
        return "winget install --id Tailscale.Tailscale --accept-source-agreements --accept-package-agreements"
    return "curl -fsSL https://tailscale.com/install.sh | sh"


def run_install(script: str, run=subprocess.run) -> int:
    """Run the install command interactively (sudo may prompt for a password)."""
    return run(script, shell=True, check=False).returncode


def tailscale_daemon_start_commands(system: str | None = None, which=shutil.which) -> list[list[str]]:
    """Return platform-specific commands that can start the Tailscale daemon."""
    system = system or platform_name()
    if system == "darwin":
        commands: list[list[str]] = []
        # The Homebrew formula ships tailscaled as a root launchd service.
        if which("brew"):
            commands.append(["sudo", "--preserve-env=HOME", "brew", "services", "start", "tailscale"])
        # The standalone and App Store variants start their daemon when the app opens.
        commands.append(["open", "-a", "Tailscale"])
        return commands
    if system == "windows":
        return [["sc", "start", "Tailscale"]]
    if which("systemctl"):
        return [["sudo", "systemctl", "start", "tailscaled"]]
    return [["sudo", "service", "tailscaled", "start"]]


def tailscale_status(run=subprocess.run, timeout: float = TAILSCALE_TIMEOUT_SECONDS) -> dict:
    """Return parsed `tailscale status --json`, or a dict describing the failure."""
    try:
        result = run(
            ["tailscale", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "error": "Tailscale status timed out. Tailscale may be starting or unresponsive; retry shortly.",
            "timed_out": True,
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit code {result.returncode}"
        lowered = detail.lower()
        daemon_unavailable = (
            "failed to connect to local tailscale daemon" in lowered
            or "tailscaled.sock" in lowered
        )
        return {
            "error": f"Tailscale is not authenticated or the daemon is not running ({detail}).",
            "daemon_unavailable": daemon_unavailable,
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {"error": "Could not read Tailscale session status."}
    return payload


def tailscale_daemon_unavailable(status: dict) -> bool:
    """Return whether status indicates that the local daemon needs starting."""
    return bool(status.get("daemon_unavailable"))


def start_tailscale_daemon(
    *,
    system: str | None = None,
    which=shutil.which,
    run=subprocess.run,
    print_fn: Callable[[str], None] = print,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """Start Tailscale and poll until its local API becomes reachable."""
    for command in tailscale_daemon_start_commands(system, which=which):
        print_fn(f"Tailscale daemon is not running; starting it with: {' '.join(command)}")
        try:
            result = run(
                command,
                check=False,
                timeout=TAILSCALE_DAEMON_START_COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue

        deadline = monotonic_fn() + TAILSCALE_DAEMON_START_TIMEOUT_SECONDS
        while True:
            status = tailscale_status(run=run, timeout=TAILSCALE_DAEMON_STATUS_TIMEOUT_SECONDS)
            if not status.get("timed_out") and not tailscale_daemon_unavailable(status):
                return True
            if monotonic_fn() >= deadline:
                break
            sleep_fn(TAILSCALE_DAEMON_RETRY_DELAY_SECONDS)
    return False


def tailscale_daemon_failure_message(system: str, status: dict) -> str:
    """Explain how to recover when the platform service could not be started."""
    message = "Could not start the Tailscale daemon."
    if system == "windows":
        message += " Run Gate from an Administrator shell or start the Tailscale service manually with 'sc start Tailscale'."
    detail = status.get("error") or "Check the Tailscale installation and retry."
    return f"{message} {detail}"


def tailscale_logged_in(status: dict | None = None, run=subprocess.run) -> tuple[bool, str]:
    """Check whether the Tailscale daemon is up and the user is logged in."""
    payload = status if status is not None else tailscale_status(run=run)
    if payload.get("error"):
        return False, payload["error"]
    backend_state = payload.get("BackendState", "")
    if backend_state != "Running":
        return False, f"Tailscale is not running (BackendState: {backend_state!r})."
    return True, ""


def operator_allows_serve(run=subprocess.run, timeout: float = TAILSCALE_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Check whether the current user may modify serve/funnel config.

    Reading funnel status works without extra permissions, but writing a serve
    config does not. The authoritative signal is the OperatorUser preference:
    it must be the current user, or Gate's `tailscale funnel --bg=false` will be
    denied with "Access denied: serve config denied".

    Returns (permission_ok, diagnostic).
    """
    try:
        result = run(
            ["tailscale", "debug", "prefs"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "Tailscale prefs check timed out."
    if result.returncode == 0:
        try:
            prefs = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return True, "Could not read Tailscale prefs."
        operator = prefs.get("OperatorUser")
        user = current_user()
        if operator == user:
            return True, ""
        if operator:
            return False, f"Tailscale operator is {operator!r}, not {user!r}."
        return False, "Tailscale operator is not set."
    # Older CLI builds may refuse `debug prefs`; fall back to probing funnel
    # status, which at least surfaces explicit permission denials.
    try:
        probe = run(
            ["tailscale", "funnel", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "Tailscale Funnel status timed out."
    combined = f"{probe.stdout}\n{probe.stderr}"
    if probe.returncode == 0:
        return True, ""
    lowered = combined.lower()
    if "denied" in lowered or "permission" in lowered:
        return False, combined.strip()
    return True, ""


def fix_operator_permission(run=subprocess.run) -> int:
    """Allow the current user to manage serve/funnel config without root."""
    user = current_user()
    if not user:
        return 1
    return run(["sudo", "tailscale", "set", f"--operator={user}"], check=False).returncode


def funnel_summary(run=subprocess.run, timeout: float = TAILSCALE_TIMEOUT_SECONDS) -> str:
    try:
        result = run(
            ["tailscale", "funnel", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "Tailscale Funnel status timed out."
    combined = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        lowered = combined.lower()
        if "funnel" in lowered and "not enabled" in lowered:
            return (
                "Funnel is not enabled for this node. Enable it in the Tailscale admin console "
                f"({FUNNEL_ADMIN_URL}, Machine settings → Enable Funnel), then retry."
            )
        return combined or f"Tailscale Funnel status failed (exit code {result.returncode})."
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return combined or "Tailscale Funnel is available."
    funnel = payload.get("Funnel", payload.get("serve"))
    if funnel:
        return "Funnel is configured and ready. Gate will use its HTTPS URL automatically."
    return "Funnel is available for this node; Gate will start it on launch."


def ensure_tailscale(
    *,
    which=shutil.which,
    platform: str | None = None,
    input_fn: Callable[[str], str] = input,
    run=subprocess.run,
    print_fn: Callable[[str], None] = print,
) -> tuple[bool, str]:
    """Install, log in, and grant serve permissions so Gate can use Tailscale.

    Returns (ready, diagnostic). Each step is skipped when already satisfied.
    """
    system = platform or platform_name()
    if tailscale_bin(which) is None:
        script = tailscale_install_script(system)
        print_fn("Tailscale CLI is not installed.")
        if not _ask(f"Install it now with:\n  {script}\nProceed?", input_fn=input_fn):
            return False, "Tailscale is required for TUNNEL_PROVIDER=tailscale. Install it and retry."
        code = run_install(script, run=run)
        if code != 0 or tailscale_bin(which) is None:
            return False, "Tailscale installation failed. Install it manually and retry."

    payload = tailscale_status(run=run)
    if payload.get("timed_out"):
        return False, payload["error"]
    if tailscale_daemon_unavailable(payload):
        if not start_tailscale_daemon(
            system=system,
            which=which,
            run=run,
            print_fn=print_fn,
        ):
            return False, tailscale_daemon_failure_message(system, payload)
        payload = tailscale_status(run=run)

    logged_in, detail = tailscale_logged_in(payload, run=run)
    if not logged_in:
        if not _ask(f"Log in now?\n  {detail}\n\nRun 'sudo tailscale up' (opens a login URL)?", input_fn=input_fn):
            return False, "Log in with 'sudo tailscale up' (or 'tailscale up') and retry."
        if run(["sudo", "tailscale", "up"], check=False).returncode != 0:
            return False, "Tailscale login failed. Run 'sudo tailscale up' and retry."
        logged_in, detail = tailscale_logged_in(run=run)
        if not logged_in:
            return False, detail

    if system != "windows":
        allowed, diagnostic = operator_allows_serve(run=run)
        if not allowed:
            user = current_user()
            if not _ask(
                f"Tailscale blocks non-root serve config:\n  {diagnostic}\n\n"
                f"Run 'sudo tailscale set --operator={user}' once to allow it?",
                input_fn=input_fn,
            ):
                return False, (
                    f"Run 'sudo tailscale set --operator={user}' once, then retry."
                )
            if fix_operator_permission(run=run) != 0:
                return False, "Could not set the Tailscale operator. Run the sudo command manually and retry."

    return True, funnel_summary(run=run)


def command_connect_ts() -> int:
    ready, message = ensure_tailscale()
    if not ready:
        print(f"✗ Tailscale is not ready: {message}")
        return 1
    print("✓ Tailscale is ready for Gate.")
    print(f"  {message}")
    print("Start Gate with the Tailscale tunnel:")
    print()
    print("  TUNNEL_PROVIDER=tailscale gate")
    return 0
