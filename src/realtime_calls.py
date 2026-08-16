from __future__ import annotations

import hashlib
import json
import logging
import threading
import re
import secrets
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

ACTIVE_STATUSES = {"starting", "running"}
QUEUED_STATUSES = {"queued", "waiting"}
MAX_PREVIEW_CHARS = 500
MAX_PURPOSE_CHARS = 240
MAX_TOOL_CHARS = 80
MAX_COMMAND_CHARS = 8_000
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
LOGGER = logging.getLogger(__name__)


def _opaque_session_digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def auto_conversation_id(session_id: str) -> str:
    return f"conv_auto_{_opaque_session_digest(session_id)}"


def session_ref(session_id: str) -> str:
    return f"mcp_{_opaque_session_digest(session_id)}"


def sanitize_command(value: str) -> str:
    """Keep shell layout while removing terminal escape/control sequences."""
    value = _ANSI_RE.sub("", value)
    return "".join(char for char in value if char in "\n\t" or (char.isprintable() and ord(char) >= 32))


def normalize_log_ref(value: str | Path | None) -> str | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    name = path.name
    if not name.endswith(".log") or not name:
        return None
    return f"logs/commands/{name}"


def _snapshot_log_ref(call: dict) -> str | None:
    if call.get("log_ref") is not None:
        return normalize_log_ref(call.get("log_ref"))
    # The runner supplies an internal absolute Path; only its safe basename is persisted.
    value = call.get("log_path")
    if value:
        name = Path(str(value)).name
        return normalize_log_ref(name)
    return None


def read_call_log(path: str | Path | None, offset: int = 0, limit: int | None = None) -> dict:
    """Read an existing call log defensively; rotation/deletion is not fatal."""
    empty = {"text": "", "offset": 0, "size": 0, "rotated": True}
    if path is None:
        return empty

    log_path = Path(path)
    try:
        size = log_path.stat().st_size
        start = max(0, int(offset))
        if start > size:
            return {**empty, "size": size}

        byte_count = None if limit is None else max(0, int(limit))
        with log_path.open("rb") as handle:
            handle.seek(start)
            content = handle.read(byte_count)
    except OSError:
        return empty

    return {
        "text": content.decode("utf-8", errors="replace"),
        "offset": start + len(content),
        "size": size,
        "rotated": False,
    }


def infer_purpose(command: str | None) -> str:
    value = " ".join((command or "").split())
    if not value:
        return "No purpose"
    executable = value.split()[0].rsplit("/", 1)[-1]
    common = {
        "pytest": "Run tests",
        "npm": "Run npm command",
        "git": "Run git command",
        "docker": "Run Docker command",
        "python": "Run Python command",
        "python3": "Run Python command",
        "cat": "Read file",
        "rg": "Search files",
    }
    return common.get(executable, f"Run {executable}")


def single_line(value: str | None) -> str:
    collapsed = " ".join((value or "").split())
    return "".join(character for character in collapsed if character.isprintable())


def shorten(value: str, width: int) -> str:
    width = max(1, int(width))
    value = single_line(value)
    if len(value) <= width:
        return value
    if width <= 3:
        return "." * width
    return value[: width - 3] + "..."


def sort_key(call: dict) -> tuple[int, int, str]:
    status = call.get("status", "")
    if status in ACTIVE_STATUSES:
        rank = 0
    elif status in QUEUED_STATUSES:
        rank = 1
    else:
        rank = 2
    timestamp = call.get("started_at") or call.get("created_at") or ""
    missing_timestamp = 0 if timestamp else 1
    descending_timestamp = "".join(chr(0x10FFFF - ord(char)) for char in timestamp)
    return rank, missing_timestamp, descending_timestamp


class RealtimeCallStore:
    def __init__(
        self,
        max_entries: int = 200,
        snapshot_path: Path | None = None,
        redact_text: Callable[[str], str] | None = None,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.snapshot_path = Path(snapshot_path) if snapshot_path else None
        self.redact_text = redact_text or (lambda value: value)
        self._active: dict[str, dict] = {}
        self._recent: deque[dict] = deque(maxlen=self.max_entries)
        self._lock = threading.RLock()
        self._write_snapshot()

    def update(self, call: dict) -> None:
        item = self._sanitize(call)
        execution_id = item["execution_id"]
        with self._lock:
            if item["status"] in ACTIVE_STATUSES | QUEUED_STATUSES:
                self._active[execution_id] = item
                self._trim_queued()
            else:
                self._active.pop(execution_id, None)
                self._recent = deque(
                    (entry for entry in self._recent if entry["execution_id"] != execution_id),
                    maxlen=self.max_entries,
                )
                self._recent.appendleft(item)
            self._write_snapshot()

    def start_activity(
        self,
        *,
        tool: str,
        kind: str = "tool",
        purpose: str | None = None,
        conversation_id: str | None = None,
        session_ref: str | None = None,
        request_id: str | None = None,
        client_id: str | None = None,
        preview: str | None = None,
        parent_execution_id: str | None = None,
    ) -> str:
        activity_id = f"activity_{secrets.token_hex(8)}"
        now = datetime.now(UTC).isoformat()
        self.update({
            "execution_id": activity_id,
            "status": "running",
            "created_at": now,
            "started_at": now,
            "finished_at": None,
            "duration_ms": 0,
            "tool": tool,
            "kind": kind,
            "purpose": purpose,
            "conversation_id": conversation_id,
            "session_ref": session_ref,
            "request_id": request_id,
            "client_id": client_id,
            "preview": preview,
            "parent_execution_id": parent_execution_id,
        })
        return activity_id

    def finish_activity(self, activity_id: str, *, status: str = "success", **updates) -> None:
        with self._lock:
            current = self._active.get(activity_id)
            if current is None:
                return
            started_at = current.get("started_at") or current.get("created_at")
            try:
                duration_ms = max(0, int(
                    (datetime.now(UTC) - datetime.fromisoformat(started_at)).total_seconds() * 1000
                ))
            except (TypeError, ValueError):
                duration_ms = int(current.get("duration_ms") or 0)
            payload = {
                **current,
                **updates,
                "execution_id": activity_id,
                "status": status,
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_ms": duration_ms,
            }
        self.update(payload)

    def _trim_queued(self) -> None:
        overflow = len(self._active) - self.max_entries
        if overflow <= 0:
            return
        queued = sorted(
            (item for item in self._active.values() if item["status"] in QUEUED_STATUSES),
            key=lambda item: item.get("created_at") or "",
        )
        for item in queued[:overflow]:
            self._active.pop(item["execution_id"], None)

    def snapshot(self) -> dict:
        with self._lock:
            calls = list(self._active.values()) + list(self._recent)
            calls.sort(key=sort_key)
            return {
                "updated_at": datetime.now(UTC).isoformat(),
                "calls": calls,
            }

    def _sanitize(self, call: dict) -> dict:
        command = sanitize_command(self.redact_text(str(call.get("command") or "")))
        command_truncated = len(command) > MAX_COMMAND_CHARS
        command = command[:MAX_COMMAND_CHARS]
        raw_preview = call.get("preview") if call.get("preview") is not None else command
        preview = self.redact_text(single_line(str(raw_preview or "")))
        purpose = self.redact_text(single_line(call.get("purpose"))) or infer_purpose(command)
        return {
            "execution_id": str(call["execution_id"]),
            "status": str(call.get("status") or "queued"),
            "created_at": call.get("created_at"),
            "started_at": call.get("started_at"),
            "finished_at": call.get("finished_at"),
            "duration_ms": int(call.get("duration_ms") or 0),
            "tool": shorten(single_line(call.get("tool")) or "run_command", MAX_TOOL_CHARS),
            "kind": shorten(single_line(call.get("kind")) or "tool", 32),
            "purpose": shorten(purpose, MAX_PURPOSE_CHARS),
            "conversation_id": single_line(call.get("conversation_id")) or None,
            "session_ref": single_line(call.get("session_ref")) or None,
            "request_id": single_line(call.get("request_id")) or None,
            "client_id": single_line(call.get("client_id")) or None,
            "parent_execution_id": single_line(call.get("parent_execution_id")) or None,
            "http_status": call.get("http_status"),
            "command": command,
            "preview": shorten(preview, MAX_PREVIEW_CHARS),
            "log_ref": _snapshot_log_ref(call),
            "command_truncated": command_truncated,
            "exit_code": call.get("exit_code"),
        }

    def _write_snapshot(self) -> None:
        if not self.snapshot_path:
            return
        temp = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8")
            try:
                temp.chmod(0o600)
            except OSError:
                pass
            temp.replace(self.snapshot_path)
        except OSError as exc:
            LOGGER.warning("Could not write realtime activity snapshot: %s", exc)
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def load_snapshot(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"updated_at": None, "calls": []}
    calls = payload.get("calls")
    return payload if isinstance(calls, list) else {"updated_at": None, "calls": []}


def format_age(call: dict, now: datetime | None = None) -> str:
    if call.get("finished_at"):
        seconds = max(0, int(call.get("duration_ms", 0)) // 1000)
    else:
        now = now or datetime.now(UTC)
        raw = call.get("started_at") or call.get("created_at")
        try:
            seconds = max(0, int((now - datetime.fromisoformat(raw)).total_seconds()))
        except (TypeError, ValueError):
            seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m{seconds:02d}s"
