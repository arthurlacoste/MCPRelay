from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TextIO

from realtime_calls import format_age, load_snapshot, shorten



def _start_time(call: dict) -> str:
    raw = call.get("started_at") or call.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw).astimezone().strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "--:--:--"


def render_snapshot(snapshot_path: Path, *, width: int = 120, height: int = 30) -> str:
    calls = load_snapshot(snapshot_path).get("calls", [])
    if not calls:
        return ""

    lines = [
        "Realtime calls",
        "",
        "STATUS    START     AGE      TOOL                  PURPOSE",
        "=" * min(width, 100),
    ]
    visible = max(1, (height - 7) // 2)
    for call in calls[:visible]:
        status = str(call.get("status", "")).upper()[:8]
        tool = shorten(str(call.get("tool") or "run_command"), 20)
        purpose = shorten(str(call.get("purpose") or "No purpose"), max(8, width - 54))
        lines.append(f"{status:<10}{_start_time(call):<10}{format_age(call):<9}{tool:<22}{purpose}")
        preview = shorten(str(call.get("preview") or ""), max(8, width - 2))
        if preview:
            lines.append(f"  {preview}")
    return "\n".join(lines)


def follow_snapshot(
    snapshot_path: Path,
    *,
    stream: TextIO | None = None,
    refresh_seconds: float = 1.0,
    interactive: bool | None = None,
) -> int:
    stream = stream or sys.stdout
    interactive = stream.isatty() if interactive is None else interactive
    try:
        while True:
            width, height = shutil.get_terminal_size((120, 30))
            output = render_snapshot(snapshot_path, width=width, height=height)
            if not output:
                print("No realtime log data found.", file=stream)
                return 1
            if interactive:
                print("\033[2J\033[H", end="", file=stream)
            print(output, file=stream, flush=True)
            if not interactive:
                return 0
            time.sleep(refresh_seconds)
    except KeyboardInterrupt:
        print("\nDetached from Gate logs.", file=stream)
        return 130
