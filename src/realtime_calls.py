from __future__ import annotations

import json
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

ACTIVE_STATUSES = {"starting", "running"}
QUEUED_STATUSES = {"queued", "waiting"}
ERROR_STATUSES = {"failed", "timeout", "interrupted", "cancelled"}
MAX_PREVIEW_CHARS = 500
MAX_PURPOSE_CHARS = 240
MAX_TOOL_CHARS = 80


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


def sort_key(call: dict) -> tuple[int, str]:
    status = call.get("status", "")
    if status in ACTIVE_STATUSES:
        rank = 0
    elif status in QUEUED_STATUSES:
        rank = 1
    elif status in ERROR_STATUSES:
        rank = 2
    else:
        rank = 3
    timestamp = call.get("started_at") or call.get("created_at") or ""
    return rank, "".join(chr(0x10FFFF - ord(char)) for char in timestamp)


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
        command = self.redact_text(single_line(call.get("command")))
        purpose = self.redact_text(single_line(call.get("purpose"))) or infer_purpose(command)
        return {
            "execution_id": str(call["execution_id"]),
            "status": str(call.get("status") or "queued"),
            "created_at": call.get("created_at"),
            "started_at": call.get("started_at"),
            "finished_at": call.get("finished_at"),
            "duration_ms": int(call.get("duration_ms") or 0),
            "tool": shorten(single_line(call.get("tool")) or "run_command", MAX_TOOL_CHARS),
            "purpose": shorten(purpose, MAX_PURPOSE_CHARS),
            "preview": shorten(command, MAX_PREVIEW_CHARS),
            "exit_code": call.get("exit_code"),
        }

    def _write_snapshot(self) -> None:
        if not self.snapshot_path:
            return
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.snapshot_path.with_suffix(self.snapshot_path.suffix + ".tmp")
        temp.write_text(json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8")
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(self.snapshot_path)


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
