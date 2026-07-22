#!/usr/bin/env python3
"""Interactive POSIX launcher for Gate services and ngrok."""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values

try:
    from src.tunnel_provider import (
        TunnelConfigurationError,
        build_tunnel_spec,
        normalize_provider,
    )
except ModuleNotFoundError:
    from tunnel_provider import (
        TunnelConfigurationError,
        build_tunnel_spec,
        normalize_provider,
    )


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("MCP_CONFIG_ROOT", BASE_DIR / "config")) / ".env"
PYTHON = BASE_DIR / ".venv" / "bin" / "python"
LOG_ROOT = Path(os.environ.get("MCP_LOG_ROOT", BASE_DIR / "logs"))
NGROK_LOG = LOG_ROOT / "ngrok.log"
TAILSCALE_LOG = LOG_ROOT / "tailscale.log"
SERVICE_LOG = LOG_ROOT / "services" / "launcher.log"
NGROK_PORT = 8761
NGROK_INSPECT_URL = "http://127.0.0.1:4040"
VERSION_FILE = BASE_DIR / "VERSION"
CHANGELOG_FILE = BASE_DIR / "CHANGELOG.md"
LATEST_RELEASE_API = "https://api.github.com/repos/spelcc/gate/releases/latest"
GATE_COMMAND = Path.home() / ".local" / "bin" / "gate"
CHATGPT_CONNECTOR_URL = (
    "https://chatgpt.com/plugins#settings/Connectors"
    "?create-connector=true&redirectAfter=%2Fplugins"
)

STOP_REQUESTED = False
UPDATE_REQUESTED = False




def version_tuple(value: str) -> tuple[int, int, int]:
    normalized = value.strip().removeprefix("v")
    parts = normalized.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid semantic version: {value}")
    return tuple(int(part) for part in parts)


def fetch_latest_release_tag() -> str | None:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Gate"},
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.load(response)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    tag = payload.get("tag_name")
    return tag if isinstance(tag, str) else None


def available_update() -> str | None:
    try:
        current = VERSION_FILE.read_text(encoding="utf-8").strip()
        latest_tag = fetch_latest_release_tag()
        if not latest_tag or version_tuple(latest_tag) <= version_tuple(current):
            return None
        return latest_tag.removeprefix("v")
    except (OSError, ValueError):
        return None


def install_update() -> int:
    return subprocess.run([str(GATE_COMMAND), "update"], check=False).returncode


def relaunch_gate() -> int:
    os.execv(str(GATE_COMMAND), [str(GATE_COMMAND)])
    return 0


def install_update_and_relaunch() -> int:
    code = install_update()
    return code if code else relaunch_gate()


def latest_changelog(version: str | None = None) -> str:
    try:
        current = version or VERSION_FILE.read_text(encoding="utf-8").strip()
        text = CHANGELOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return "Changelog unavailable."
    marker = f"## {current}"
    start = text.find(marker)
    if start < 0:
        return "No changelog entry found."
    start += len(marker)
    end = text.find("\n## ", start)
    section = text[start:end if end >= 0 else None].strip()
    return section or "No changes listed."


def control_lines(update_version: str | None = None) -> list[str]:
    lines = ["[m]    Connection details", "[c]    Changelog"]
    if update_version:
        lines.append(f"[u]    Install update {update_version}")
    lines.append("[^C]   Stop Gate")
    return lines


class StartupError(RuntimeError):
    """Raised when a managed process fails during startup."""


class ShutdownRequested(RuntimeError):
    """Raised when shutdown is requested during startup."""


class ExistingProcess:
    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        try:
            os.kill(self.pid, 0)
            return None
        except ProcessLookupError:
            return 1

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(["pid", str(self.pid)], timeout)
            time.sleep(0.05)
        return 0



def request_shutdown(*_args) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def configured_tunnel_provider() -> str:
    values = dotenv_values(CONFIG_FILE)
    return normalize_provider(os.environ.get("TUNNEL_PROVIDER") or values.get("TUNNEL_PROVIDER"))


def connection_detail_lines() -> list[str]:
    values = dotenv_values(CONFIG_FILE)
    public_url = (values.get("MCP_BASE_URL") or "").strip()
    access_secret = (values.get("OAUTH_ACCESS_SECRET") or "").strip()
    if not public_url or not access_secret:
        return ["! OAuth setup incomplete. Run: ./run.sh setup"]
    return [
        f"Public MCP:      {public_url}/mcp",
        f"Public OAuth:    {public_url}/oauth",
        f"Local MCP:       http://127.0.0.1:{NGROK_PORT}/mcp",
        f"Local OAuth:     http://127.0.0.1:{NGROK_PORT}/oauth",
        f"OAuth health:    http://127.0.0.1:{NGROK_PORT}/oauth/health",
        *([f"ngrok inspector: {NGROK_INSPECT_URL}"] if configured_tunnel_provider() == "ngrok" else []),
        f"ChatGPT setup:   {CHATGPT_CONNECTOR_URL}",
        f"Access secret:   {access_secret}",
    ]


def show_connection_details() -> None:
    print("\n\033[1;34mConnection details\033[0m")
    print("\n".join(connection_detail_lines()), flush=True)


def clear_terminal() -> None:
    print("\033[2J\033[H", end="", flush=True)


def render_screen(services, tunnel, keep_awake: str, update_version: str | None, panel: str | None) -> None:
    clear_terminal()
    print(f"\033[1;32m✓ Gateway running (PID {services.pid})\033[0m")
    provider = configured_tunnel_provider()
    if tunnel is not None:
        print(f"\033[1;32m✓ {provider} running (PID {tunnel.pid}) [{keep_awake}]\033[0m")
    else:
        print("\033[1;32m✓ external tunnel managed by user\033[0m")
    if provider == "ngrok":
        print(f"  ngrok inspector → {NGROK_INSPECT_URL}\n")
    else:
        print()
    if panel == "connections":
        print("\033[1;34mConnection details\033[0m\n")
        print("\n".join(connection_detail_lines()))
        print("\n[m] / [Esc]   Close", flush=True)
    elif panel == "changelog":
        current = VERSION_FILE.read_text(encoding="utf-8").strip()
        print(f"\033[1;34mChangelog · Gate {current}\033[0m\n")
        print(latest_changelog(current))
        print("\n[c] / [Esc]   Close", flush=True)
    else:
        print("\033[1mControls\033[0m\n")
        print("\n".join(control_lines(update_version)), flush=True)


@contextmanager
def terminal_input():
    if not sys.stdin.isatty():
        yield None
        return

    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield fd
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def log_tail(path: Path, max_lines: int = 8) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:]).strip()


def startup_failure_message(name: str, code: int, log_path: Path | None = None) -> str:
    if name != "Gateway":
        if log_path is None and name.lower() == "ngrok":
            log_path = NGROK_LOG
        suffix = f" Check {log_path}." if log_path else ""
        return f"{name} failed to start (exit {code}).{suffix}"

    details = log_tail(SERVICE_LOG)
    message = f"Gateway failed to start (exit {code})."
    if details:
        message += f"\n\nLast startup output:\n{details}"
    message += f"\n\nFull log: {SERVICE_LOG}"
    return message


GATEWAY_HEALTH_URL = f"http://127.0.0.1:{NGROK_PORT}/oauth/health"
NGROK_TUNNELS_URL = f"{NGROK_INSPECT_URL}/api/tunnels"


def wait_for_gateway_health(process: subprocess.Popen | ExistingProcess, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if STOP_REQUESTED:
            raise ShutdownRequested
        code = process.poll()
        if code is not None:
            raise StartupError(startup_failure_message("Gateway", code))
        try:
            req = urllib.request.Request(GATEWAY_HEALTH_URL, method="GET")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise StartupError("Gateway did not become ready within timeout.")


def wait_for_ngrok_ready(process: subprocess.Popen | ExistingProcess, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if STOP_REQUESTED:
            raise ShutdownRequested
        code = process.poll()
        if code is not None and not isinstance(process, ExistingProcess):
            raise StartupError(startup_failure_message("ngrok", code))
        try:
            req = urllib.request.Request(NGROK_TUNNELS_URL, method="GET")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                body = exc.read().decode("utf-8", errors="replace")
                if "Rejected host" in body:
                    raise StartupError(
                        "ngrok inspection API is blocking localhost.\n"
                        "Add '127.0.0.1' and 'localhost' to web_allow_hosts in:\n"
                        "  ~/.config/ngrok/ngrok.yml"
                    ) from exc
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    raise StartupError("ngrok did not become ready within timeout.")


def terminate_group(process: subprocess.Popen | ExistingProcess | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if isinstance(process, ExistingProcess):
            os.kill(process.pid, signal.SIGTERM)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            if isinstance(process, ExistingProcess):
                os.kill(process.pid, signal.SIGKILL)
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def start_services() -> subprocess.Popen:
    SERVICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SERVICE_LOG.open("w", encoding="utf-8") as log_file:
        return subprocess.Popen(
            [str(PYTHON), str(BASE_DIR / "start_services.py")],
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def start_tunnel() -> tuple[subprocess.Popen | ExistingProcess | None, str]:
    provider = configured_tunnel_provider()
    if provider == "external":
        return None, "user managed"
    existing = os.environ.get("GATE_EXISTING_NGROK_PID", "") if provider == "ngrok" else ""
    if existing.isdigit():
        process = ExistingProcess(int(existing))
        if process.poll() is None:
            return process, "onboarding tunnel reused"
    spec = build_tunnel_spec(provider, NGROK_PORT, LOG_ROOT)
    assert spec.command is not None and spec.log_path is not None
    command = spec.command
    label = "sleep inhibition inactive"
    if shutil.which("caffeinate"):
        command = ["caffeinate", "-i", *command]
        label = "caffeinate active"

    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    with spec.log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process, label



def monitor(services, tunnel, keep_awake: str, update_result: list[str | None] | None = None) -> int:
    global UPDATE_REQUESTED
    panel: str | None = None
    with terminal_input() as input_fd:
        render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
        while not STOP_REQUESTED:
            if services.poll() is not None:
                print("Error: Gateway stopped unexpectedly.", file=sys.stderr)
                return 1
            if tunnel is not None and tunnel.poll() is not None:
                provider = configured_tunnel_provider()
                log_path = TAILSCALE_LOG if provider == "tailscale" else NGROK_LOG
                print(f"Error: {provider} stopped. Check {log_path}.", file=sys.stderr)
                return 1
            if input_fd is None:
                time.sleep(0.2)
                continue
            readable, _, _ = select.select([input_fd], [], [], 0.2)
            if not readable:
                continue
            key = os.read(input_fd, 1).lower()
            if key == b"m":
                panel = None if panel == "connections" else "connections"
                render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
            elif key == b"c":
                panel = None if panel == "changelog" else "changelog"
                render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
            elif key == b"\x1b" and panel is not None:
                panel = None
                render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
            elif key == b"u" and update_result and update_result[0] and panel is None:
                UPDATE_REQUESTED = True
                clear_terminal()
                print(f"Updating Gate to {update_result[0]}…", flush=True)
                return 0
    return 0


def main() -> int:
    global UPDATE_REQUESTED
    services = None
    tunnel = None
    exit_code = 0
    UPDATE_REQUESTED = False
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        services = start_services()
        wait_for_gateway_health(services)
        tunnel, keep_awake = start_tunnel()
        if configured_tunnel_provider() == "ngrok" and tunnel is not None:
            wait_for_ngrok_ready(tunnel)

        update_result: list[str | None] = [None]
        def _fetch_update() -> None:
            update_result[0] = available_update()
        update_thread = threading.Thread(target=_fetch_update, daemon=True)
        update_thread.start()

        exit_code = monitor(services, tunnel, keep_awake, update_result)
    except ShutdownRequested:
        exit_code = 0
    except (OSError, StartupError, TunnelConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        if services is not None or tunnel is not None:
            print("\n⟶ stopping services…", flush=True)
            terminate_group(tunnel)
            terminate_group(services)
            print("✓ Services stopped", flush=True)

    if UPDATE_REQUESTED:
        return install_update_and_relaunch()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
