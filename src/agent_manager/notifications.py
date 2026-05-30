from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import AgentRecord

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a project dependency.
    yaml = None


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = {
    "enabled": True,
    "macos": True,
    "include_url": True,
    "include_stdout_chars": 220,
}


def load_notification_config(base_dir: Path = BASE_DIR) -> dict[str, Any]:
    config_path = base_dir / "config" / "scheduler.yaml"
    if not config_path.exists() or yaml is None:
        return DEFAULT_CONFIG.copy()
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return {**DEFAULT_CONFIG, **(raw.get("notifications") or {})}


def applescript_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def compact_text(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def result_summary(result: dict[str, Any] | None, limit: int) -> str:
    if not result:
        return ""
    if result.get("error"):
        return compact_text(str(result["error"]), limit)
    stdout = str(result.get("stdout") or "")
    if stdout.strip():
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        return compact_text(" | ".join(lines[-4:]), limit)
    return compact_text(json.dumps(result, ensure_ascii=False, default=str), limit)


def notification_payload(
    record: AgentRecord,
    status: str,
    result: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    title_status = "termine" if status == "completed" else "echec"
    title = f"Agent {title_status}: {record.purpose or record.agent_id}"
    subtitle = record.metadata.get("note_title") or record.agent_id
    message_parts = [f"Status: {status}", f"ID: {record.agent_id}"]
    summary = result_summary(result, int(cfg.get("include_stdout_chars", 220)))
    if summary:
        message_parts.append(summary)
    if cfg.get("include_url", True):
        message_parts.append(f"http://localhost:8761/agents/{record.agent_id}")
    return {
        "title": compact_text(title, 80),
        "subtitle": compact_text(str(subtitle), 80),
        "message": compact_text(" - ".join(message_parts), 420),
    }


def send_macos_notification(payload: dict[str, str]) -> None:
    script = (
        f'display notification "{applescript_quote(payload["message"])}" '
        f'with title "{applescript_quote(payload["title"])}" '
        f'subtitle "{applescript_quote(payload["subtitle"])}"'
    )
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def notify_agent_finished(
    record: AgentRecord,
    status: str,
    result: dict[str, Any] | None,
    *,
    base_dir: Path = BASE_DIR,
) -> dict[str, Any]:
    config = load_notification_config(base_dir)
    if not config.get("enabled", True):
        return {"ok": True, "sent": False, "reason": "disabled"}
    payload = notification_payload(record, status, result, config)
    if config.get("macos", True):
        send_macos_notification(payload)
        return {"ok": True, "sent": True, "channel": "macos", "payload": payload}
    return {"ok": True, "sent": False, "reason": "no_channel", "payload": payload}
