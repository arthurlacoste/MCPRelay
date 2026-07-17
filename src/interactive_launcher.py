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
import time
import tty
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("MCP_CONFIG_ROOT", BASE_DIR / "config")) / ".env"
PYTHON = BASE_DIR / ".venv" / "bin" / "python"
LOG_ROOT = Path(os.environ.get("MCP_LOG_ROOT", BASE_DIR / "logs"))
NGROK_LOG = LOG_ROOT / "ngrok.log"
SERVICE_LOG = LOG_ROOT / "services" / "launcher.log"
NGROK_PORT = 8761
NGROK_INSPECT_URL = "http://127.0.0.1:4040"
VERSION_FILE = BASE_DIR / "VERSION"
LATEST_RELEASE_API = "https://api.github.com/repos/arthurlacoste/gate/releases/latest"
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


def show_connection_details() -> None:
    values = dotenv_values(CONFIG_FILE)
    public_url = (values.get("MCP_BASE_URL") or "").strip()
    access_secret = (values.get("OAUTH_ACCESS_SECRET") or "").strip()
    if not public_url or not access_secret:
        print("! OAuth setup incomplete. Run: ./run.sh setup", flush=True)
        return

    print("\n\033[1;34mConnection details\033[0m")
    print(f"Public MCP:      {public_url}/mcp")
    print(f"Public OAuth:    {public_url}/oauth")
    print(f"Local MCP:       http://127.0.0.1:{NGROK_PORT}/mcp")
    print(f"Local OAuth:     http://127.0.0.1:{NGROK_PORT}/oauth")
    print(f"OAuth health:    http://127.0.0.1:{NGROK_PORT}/oauth/health")
    print(f"ngrok inspector: {NGROK_INSPECT_URL}")
    print(f"ChatGPT setup:   {CHATGPT_CONNECTOR_URL}")
    print(f"Access secret:   {access_secret}", flush=True)


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


def startup_failure_message(name: str, code: int) -> str:
    if name != "Gateway":
        return f"{name} failed to start (exit {code}). Check {NGROK_LOG}."

    details = log_tail(SERVICE_LOG)
    message = f"Gateway failed to start (exit {code})."
    if details:
        message += f"\n\nLast startup output:\n{details}"
    message += f"\n\nFull log: {SERVICE_LOG}"
    return message


def wait_for_start(process: subprocess.Popen, name: str, seconds: float = 2) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if STOP_REQUESTED:
            raise ShutdownRequested
        code = process.poll()
        if code is not None:
            raise StartupError(startup_failure_message(name, code))
        time.sleep(0.1)


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


def start_ngrok() -> tuple[subprocess.Popen | ExistingProcess, str]:
    existing = os.environ.get("GATE_EXISTING_NGROK_PID", "")
    if existing.isdigit():
        process = ExistingProcess(int(existing))
        if process.poll() is None:
            return process, "onboarding tunnel reused"
    if shutil.which("caffeinate"):
        command = ["caffeinate", "-i", "ngrok", "http", str(NGROK_PORT)]
        label = "caffeinate active"
    else:
        command = ["ngrok", "http", str(NGROK_PORT)]
        label = "sleep inhibition inactive"

    with NGROK_LOG.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=BASE_DIR,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process, label




def monitor(services: subprocess.Popen, ngrok: subprocess.Popen, update_version: str | None = None) -> int:
    global UPDATE_REQUESTED
    with terminal_input() as input_fd:
        controls = "Press m for connection details"
        if update_version:
            controls += f". Update {update_version} available — press u to install"
        print(f"\n{controls}. Ctrl+C to stop.", flush=True)
        while not STOP_REQUESTED:
            if services.poll() is not None:
                print("Error: Gateway stopped unexpectedly.", file=sys.stderr)
                return 1
            if ngrok.poll() is not None:
                print(f"Error: ngrok stopped. Check {NGROK_LOG}.", file=sys.stderr)
                return 1

            if input_fd is None:
                time.sleep(0.2)
                continue

            readable, _, _ = select.select([input_fd], [], [], 0.2)
            if readable:
                key = os.read(input_fd, 1).lower()
                if key == b"m":
                    show_connection_details()
                elif key == b"u" and update_version:
                    UPDATE_REQUESTED = True
                    print(f"\nUpdating Gate to {update_version}…", flush=True)
                    return 0
    return 0


def main() -> int:
    global UPDATE_REQUESTED
    services = None
    ngrok = None
    exit_code = 0
    UPDATE_REQUESTED = False
    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    try:
        services = start_services()
        wait_for_start(services, "Gateway")
        ngrok, keep_awake = start_ngrok()
        wait_for_start(ngrok, "ngrok")

        print(f"\033[1;32m✓ Gateway running (PID {services.pid})\033[0m")
        print(f"\033[1;32m✓ ngrok running (PID {ngrok.pid}) [{keep_awake}]\033[0m")
        print(f"  ngrok inspector → {NGROK_INSPECT_URL}")
        update_version = available_update()
        exit_code = monitor(services, ngrok, update_version)
    except ShutdownRequested:
        exit_code = 0
    except (OSError, StartupError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        if services is not None or ngrok is not None:
            print("\n⟶ stopping services…", flush=True)
            terminate_group(ngrok)
            terminate_group(services)
            print("✓ Services stopped", flush=True)

    if UPDATE_REQUESTED:
        return install_update()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
