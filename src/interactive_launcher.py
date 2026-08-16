#!/usr/bin/env python3
"""Interactive POSIX launcher for Gate services and ngrok."""

from __future__ import annotations

import json
import os
import re
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
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values
from changelog_parser import changelog_section
from ngrok_target import gateway_health_url, resolve_ngrok_target
from terminal_rendering import TerminalFrameRenderer, restore_terminal_output

try:
    from src.tunnel_provider import (
        TunnelConfigurationError,
        build_tunnel_spec,
        cloudflared_public_url,
        cloudflared_registered,
        normalize_provider,
        tailscale_public_url,
    )
except ModuleNotFoundError:
    from tunnel_provider import (
        TunnelConfigurationError,
        build_tunnel_spec,
        cloudflared_public_url,
        cloudflared_registered,
        normalize_provider,
        tailscale_public_url,
    )


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("MCP_CONFIG_ROOT", BASE_DIR / "config")) / ".env"
PYTHON = BASE_DIR / ".venv" / "bin" / "python"
LOG_ROOT = Path(os.environ.get("MCP_LOG_ROOT", BASE_DIR / "logs"))
NGROK_LOG = LOG_ROOT / "ngrok.log"
TAILSCALE_LOG = LOG_ROOT / "tailscale.log"
CLOUDFLARED_LOG = LOG_ROOT / "cloudflared.log"
SERVICE_LOG = LOG_ROOT / "services" / "launcher.log"
REALTIME_CALLS_FILE = LOG_ROOT / "realtime_calls.json"
REALTIME_REFRESH_SECONDS = max(0.25, int(os.environ.get("GATE_REALTIME_REFRESH_MS", "1000")) / 1000)
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
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def sanitize_command(value: str) -> str:
    """Keep shell layout while removing terminal escape/control sequences."""
    value = _ANSI_RE.sub("", value)
    return "".join(char for char in value if char in "\n\t" or (char.isprintable() and ord(char) >= 32))


def read_call_log(path: str | Path | None, offset: int = 0, limit: int | None = None) -> dict:
    """Read a call log defensively using byte offsets and an optional byte bound."""
    if not path:
        return {"text": "", "offset": 0, "size": 0, "rotated": True}
    try:
        path = Path(path)
        size = path.stat().st_size
        safe_offset = max(0, int(offset))
        if safe_offset > size:
            return {"text": "", "offset": 0, "size": size, "rotated": True}
        with path.open("rb") as handle:
            handle.seek(safe_offset)
            content = handle.read() if limit is None else handle.read(max(0, int(limit)))
        return {"text": content.decode("utf-8", errors="replace"), "offset": safe_offset + len(content), "size": size, "rotated": False}
    except OSError:
        return {"text": "", "offset": 0, "size": 0, "rotated": True}




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
    section = changelog_section(text, current)
    if section is None:
        return "No changelog entry found."
    return section or "No changes listed."


def control_lines(update_version: str | None = None) -> list[str]:
    lines = ["[m]    Connection details", "[c]    Changelog", "[r]    Realtime calls"]
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


def configured_cloudflared_tunnel_name() -> str:
    values = dotenv_values(CONFIG_FILE)
    return (os.environ.get("CLOUDFLARED_TUNNEL_NAME") or values.get("CLOUDFLARED_TUNNEL_NAME") or "").strip()


def connection_detail_lines() -> list[str]:
    values = dotenv_values(CONFIG_FILE)
    public_url = (values.get("MCP_BASE_URL") or "").strip()
    access_secret = (values.get("OAUTH_ACCESS_SECRET") or "").strip()
    if not public_url or not access_secret:
        return ["! OAuth setup incomplete. Run: ./run.sh setup"]
    return [
        f"Public MCP:      {public_url}/mcp",
        f"Public OAuth:    {public_url}/oauth",
        f"Public realtime: {public_url}/rt",
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


def _single_line(value: str | None) -> str:
    collapsed = " ".join((value or "").split())
    return "".join(character for character in collapsed if character.isprintable())


def shorten(value: str, width: int) -> str:
    width = max(1, int(width))
    value = _single_line(value)
    if len(value) <= width:
        return value
    if width <= 3:
        return "." * width
    return value[: width - 3] + "..."


def resolve_realtime_log(log_ref: str | None) -> Path | None:
    if not isinstance(log_ref, str) or not log_ref:
        return None
    relative = Path(log_ref)
    if relative.is_absolute() or relative.parts != ("logs", "commands", relative.name) or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    commands_root = (LOG_ROOT / "commands").resolve()
    candidate = (commands_root / relative.name).resolve()
    try:
        candidate.relative_to(commands_root)
    except ValueError:
        return None
    return candidate


def load_snapshot(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"updated_at": None, "calls": []}
    return payload if isinstance(payload.get("calls"), list) else {"updated_at": None, "calls": []}


def format_age(call: dict, now: datetime | None = None) -> str:
    elapsed = int(call.get("duration_ms") or 0) // 1000
    if not call.get("finished_at"):
        try:
            started = datetime.fromisoformat(call.get("started_at") or call.get("created_at"))
            elapsed = int(((now or datetime.now(UTC)) - started).total_seconds())
        except (TypeError, ValueError):
            elapsed = 0
    elapsed = max(0, elapsed)
    return f"{elapsed}s" if elapsed < 60 else f"{elapsed // 60}m{elapsed % 60:02d}s"


def _start_time(call: dict) -> str:
    raw = call.get("started_at") or call.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "--:--:--"


def realtime_rows(errors_only: bool = False) -> list[dict]:
    calls = load_snapshot(REALTIME_CALLS_FILE).get("calls", [])
    if errors_only:
        calls = [call for call in calls if call.get("status") in {"failed", "timeout", "interrupted", "cancelled"}]
    return calls


def build_realtime_panel(
    selected: int = 0,
    errors_only: bool = False,
    paused: bool = False,
    details: bool = False,
    detail_offset: int = 0,
    follow_tail: bool = True,
) -> list[str]:
    width, height = shutil.get_terminal_size((120, 30))
    calls = realtime_rows(errors_only)
    selected = max(0, min(selected, max(0, len(calls) - 1)))
    mode = "PAUSED" if paused else "LIVE"
    filter_label = "errors" if errors_only else "all"
    lines = [f"\033[1;34mRealtime calls\033[0m  {mode}  filter:{filter_label}", ""]

    if details and calls:
        call = calls[selected]
        lines.extend([
            f"Status:   {call.get('status', '').upper()}",
            f"Kind:     {call.get('kind', 'tool')}",
            f"Tool:     {call.get('tool', 'run_command')}",
            f"Purpose:  {call.get('purpose', 'No purpose')}",
            f"Conversation: {call.get('conversation_id') or '-'}",
            f"Session:  {call.get('session_ref') or '-'}",
            f"Request:  {call.get('request_id') or '-'}",
            f"Client:   {call.get('client_id') or '-'}",
            f"HTTP:     {call.get('http_status') if call.get('http_status') is not None else '-'}",
            f"Started:  {_start_time(call)}",
            f"Age:      {format_age(call)}",
            f"Exit:     {call.get('exit_code')}",
        ])
        has_terminal = bool(call.get("command") or call.get("preview") or call.get("log_ref"))
        if has_terminal:
            lines.append("Command:")
            command = sanitize_command(call.get("command") or call.get("preview", "") or "(unavailable)")
            lines.extend(command.splitlines() or [""])
            if call.get("command_truncated"):
                lines.append("[command truncated at 8000 characters]")
            log = read_call_log(resolve_realtime_log(call.get("log_ref")), 0)
            log_lines = log["text"].splitlines()
            command_lines = max(1, len(command.splitlines()))
            truncation_lines = 1 if call.get("command_truncated") else 0
            visible = max(1, height - 20 - command_lines - truncation_lines)
            shown = log_lines[-visible:] if follow_tail else log_lines[detail_offset:detail_offset + visible]
            lines.extend(["", "Terminal log" + (" (following)" if follow_tail else "") + ":"])
            lines.extend(shown or ["(log unavailable or empty)" if log["rotated"] else "(log empty)"])
            controls = "[Enter] Back  [q/Esc] Exit  [↑/↓] Scroll  [f] Follow tail"
        else:
            controls = "[Enter] Back  [q/Esc] Exit"
        lines.extend(["", controls])
        return lines

    lines.extend([
        "STATUS    START     AGE      TOOL                  CONVERSATION         PURPOSE",
        "=" * min(width, 120),
    ])
    visible = max(1, (height - 9) // 2)
    for index, call in enumerate(calls[:visible]):
        marker = ">" if index == selected else " "
        status = call.get("status", "").upper()[:8]
        tool = shorten(call.get("tool", "run_command"), 20)
        conversation = shorten(call.get("conversation_id") or "-", 18)
        purpose = shorten(call.get("purpose", "No purpose"), max(8, width - 75))
        lines.append(
            f"{marker}{status:<9} {_start_time(call):<9} {format_age(call):<8} "
            f"{tool:<21} {conversation:<20} {purpose}"
        )
        preview = call.get("preview", "")
        if preview:
            lines.append(f"  {shorten(preview, max(8, width - 2))}")
    if not calls:
        lines.append("No calls yet.")
    lines.extend(["", "[q/Esc] Exit  [p] Pause  [r] Refresh  [e] Errors  [a] All  [↑/↓] Navigate  [Enter] Details"])
    return lines


def render_realtime_panel(
    selected: int = 0,
    errors_only: bool = False,
    paused: bool = False,
    details: bool = False,
    detail_offset: int = 0,
    follow_tail: bool = True,
    *,
    renderer: TerminalFrameRenderer | None = None,
    force_full: bool = False,
) -> None:
    lines = build_realtime_panel(selected, errors_only, paused, details, detail_offset, follow_tail)
    if renderer is None:
        clear_terminal()
        print("\n".join(lines), flush=True)
        return
    renderer.render(lines, full=force_full)

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

    restore_terminal_output()
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield fd
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        finally:
            restore_terminal_output()


def log_tail(path: Path, max_lines: int = 8) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:]).strip()


def startup_failure_message(name: str, code: int, log_path: Path | None = None) -> str:
    if name != "Gateway":
        if log_path is None:
            log_path = {
                "ngrok": NGROK_LOG,
                "tailscale": TAILSCALE_LOG,
                "cloudflare": CLOUDFLARED_LOG,
            }.get(name.lower())
        suffix = f" Check {log_path}." if log_path else ""
        return f"{name} failed to start (exit {code}).{suffix}"

    details = log_tail(SERVICE_LOG)
    message = f"Gateway failed to start (exit {code})."
    if details:
        message += f"\n\nLast startup output:\n{details}"
    message += f"\n\nFull log: {SERVICE_LOG}"
    return message


GATEWAY_HEALTH_URL = gateway_health_url(NGROK_PORT)
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




def wait_for_tailscale_ready(process: subprocess.Popen | ExistingProcess, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise StartupError(startup_failure_message("tailscale", code))
        try:
            if tailscale_public_url():
                return
        except TunnelConfigurationError:
            pass
        time.sleep(0.2)
    raise StartupError(f"Tailscale Funnel did not become ready. Check {TAILSCALE_LOG}.")


def wait_for_cloudflared_ready(process: subprocess.Popen | ExistingProcess, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if STOP_REQUESTED:
            raise ShutdownRequested
        code = process.poll()
        if code is not None and not isinstance(process, ExistingProcess):
            raise StartupError(startup_failure_message("cloudflare", code))
        if cloudflared_public_url(CLOUDFLARED_LOG) or cloudflared_registered(CLOUDFLARED_LOG):
            return
        time.sleep(0.2)
    raise StartupError(f"Cloudflare Tunnel did not become ready. Check {CLOUDFLARED_LOG}.")

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
    existing_env = {
        "ngrok": "GATE_EXISTING_NGROK_PID",
        "cloudflare": "GATE_EXISTING_CLOUDFLARED_PID",
    }.get(provider)
    existing = os.environ.get(existing_env, "") if existing_env else ""
    if existing.isdigit():
        process = ExistingProcess(int(existing))
        if process.poll() is None:
            return process, "onboarding tunnel reused"
    spec = build_tunnel_spec(
        provider,
        NGROK_PORT,
        LOG_ROOT,
        ngrok_target=resolve_ngrok_target(NGROK_PORT) if provider == "ngrok" else None,
        cloudflared_tunnel_name=configured_cloudflared_tunnel_name() if provider == "cloudflare" else None,
    )
    if spec.command is None or spec.log_path is None:
        raise StartupError(f"{spec.display_name} has no launch command or log path.")
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
    realtime_selected = 0
    realtime_paused = False
    realtime_errors = False
    realtime_details = False
    realtime_detail_offset = 0
    realtime_follow_tail = True
    last_realtime_render = 0.0
    realtime_renderer = TerminalFrameRenderer()
    with terminal_input() as input_fd:
        render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
        while not STOP_REQUESTED:
            if services.poll() is not None:
                print("Error: Gateway stopped unexpectedly.", file=sys.stderr)
                return 1
            if tunnel is not None and tunnel.poll() is not None:
                provider = configured_tunnel_provider()
                log_path = {
                    "tailscale": TAILSCALE_LOG,
                    "cloudflare": CLOUDFLARED_LOG,
                }.get(provider, NGROK_LOG)
                print(f"Error: {provider} stopped. Check {log_path}.", file=sys.stderr)
                return 1
            if panel == "realtime" and not realtime_paused and time.monotonic() - last_realtime_render >= REALTIME_REFRESH_SECONDS:
                render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, realtime_detail_offset, realtime_follow_tail, renderer=realtime_renderer)
                last_realtime_render = time.monotonic()
            if input_fd is None:
                time.sleep(0.2)
                continue
            readable, _, _ = select.select([input_fd], [], [], 0.2)
            if not readable:
                continue
            key = os.read(input_fd, 1).lower()
            if panel == "realtime":
                if key == b"\x1b":
                    more, _, _ = select.select([input_fd], [], [], 0.02)
                    if more:
                        sequence = os.read(input_fd, 2)
                        key = b"up" if sequence == b"[A" else b"down" if sequence == b"[B" else b"\x1b"
                if key in {b"q", b"\x1b"}:
                    panel = None
                    realtime_details = False
                    realtime_renderer.finish()
                    render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
                elif key == b"p":
                    realtime_paused = not realtime_paused
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, renderer=realtime_renderer)
                elif key == b"r":
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, realtime_detail_offset, realtime_follow_tail, renderer=realtime_renderer)
                elif key == b"e":
                    realtime_errors = True
                    realtime_selected = 0
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, renderer=realtime_renderer)
                elif key == b"a":
                    realtime_errors = False
                    realtime_selected = 0
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, renderer=realtime_renderer)
                elif key in {b"j", b"down"}:
                    if realtime_details:
                        realtime_follow_tail = False
                        realtime_detail_offset += 1
                    else:
                        realtime_selected += 1
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, realtime_detail_offset, realtime_follow_tail, renderer=realtime_renderer)
                elif key in {b"k", b"up"}:
                    if realtime_details:
                        realtime_follow_tail = False
                        realtime_detail_offset = max(0, realtime_detail_offset - 1)
                    else:
                        realtime_selected = max(0, realtime_selected - 1)
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, realtime_detail_offset, realtime_follow_tail, renderer=realtime_renderer)
                elif key in {b"\r", b"\n"}:
                    realtime_details = not realtime_details
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, renderer=realtime_renderer)
                elif realtime_details and key in {b"f"}:
                    realtime_follow_tail = not realtime_follow_tail
                    render_realtime_panel(realtime_selected, realtime_errors, realtime_paused, realtime_details, realtime_detail_offset, realtime_follow_tail, renderer=realtime_renderer)
                continue
            if key == b"m":
                panel = None if panel == "connections" else "connections"
                render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
            elif key == b"c":
                panel = None if panel == "changelog" else "changelog"
                render_screen(services, tunnel, keep_awake, update_result[0] if update_result else None, panel)
            elif key == b"r":
                panel = "realtime"
                realtime_selected = 0
                realtime_paused = False
                realtime_errors = False
                realtime_details = False
                realtime_detail_offset = 0
                realtime_follow_tail = True
                render_realtime_panel(renderer=realtime_renderer, force_full=True)
                last_realtime_render = time.monotonic()
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
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, request_shutdown)

    try:
        services = start_services()
        wait_for_gateway_health(services)
        tunnel, keep_awake = start_tunnel()
        provider = configured_tunnel_provider()
        if provider == "ngrok" and tunnel is not None:
            wait_for_ngrok_ready(tunnel)
        elif provider == "tailscale" and tunnel is not None:
            wait_for_tailscale_ready(tunnel)
        elif provider == "cloudflare" and tunnel is not None:
            wait_for_cloudflared_ready(tunnel)

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
        restore_terminal_output()
        if services is not None or tunnel is not None:
            try:
                print("\n⟶ stopping services…", flush=True)
            except (BrokenPipeError, OSError):
                pass
            terminate_group(tunnel)
            terminate_group(services)
            try:
                print("✓ Services stopped", flush=True)
            except (BrokenPipeError, OSError):
                pass

    if UPDATE_REQUESTED:
        return install_update_and_relaunch()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
