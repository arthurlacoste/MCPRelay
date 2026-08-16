from __future__ import annotations

import logging
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from command_queue import process_group_options, terminate_process_tree

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockingCommandResult:
    command: str
    exit_code: int | None
    timed_out: bool
    timeout_seconds: float
    stdout: str
    stderr: str
    log_path: Path
    duration_ms: int
    max_output_chars: int

    def render(self) -> str:
        stdout, stdout_truncated = self._bounded(self.stdout)
        stderr, stderr_truncated = self._bounded(self.stderr)
        parts = [f"COMMAND: {self.command}", f"EXIT CODE: {self.exit_code}"]
        if self.timed_out:
            parts.append(f"TIMED OUT AFTER: {self.timeout_seconds:g}s")
        parts.extend(["", "STDOUT:", stdout])
        if stderr:
            parts.extend(["", "STDERR:", stderr])
        parts.extend(["", f"Full log: {self.log_path}"])
        if stdout_truncated or stderr_truncated:
            parts.append(
                f"\nOutput truncated at {self.max_output_chars} characters per stream. "
                "See log file for full output."
            )
        return "\n".join(parts)

    def _bounded(self, value: str) -> tuple[str, bool]:
        if len(value) <= self.max_output_chars:
            return value, False
        return value[:self.max_output_chars] + "\n… [output truncated]", True


class BlockingCommandRunner:
    def __init__(
        self,
        log_dir: Path,
        worker_limit: int = 4,
        max_output_chars: int = 50_000,
        redact_text=None,
        state_observer: Callable[[dict], None] | None = None,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars
        self.redact_text = redact_text or (lambda value: value)
        self.state_observer = state_observer
        self._capacity = threading.BoundedSemaphore(max(1, int(worker_limit)))

    def run(
        self,
        command: str,
        cwd: str | Path | None = None,
        timeout_seconds: float = 300,
        purpose: str | None = None,
        conversation_id: str | None = None,
    ) -> BlockingCommandResult:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        safe_timeout = max(0.1, min(float(timeout_seconds), 86_400.0))
        resolved_cwd = self._resolve_cwd(cwd)
        started = time.monotonic()
        created_at = datetime.now(UTC).isoformat()
        log_path = self._new_log_path()
        execution_id = log_path.stem
        display_command = self.redact_text(command)
        state = {
            "execution_id": execution_id,
            "status": "waiting",
            "command": display_command,
            "purpose": purpose,
            "conversation_id": conversation_id,
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "duration_ms": 0,
            "exit_code": None,
            "tool": "run_command",
            "log_path": str(log_path),
            "log_ref": f"logs/commands/{log_path.name}",
        }
        self._publish_state(state)
        with self._capacity:
            log_path.write_text(f"COMMAND:\n{display_command}\n\n", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=resolved_cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    **process_group_options(),
                )
            except Exception:
                self._publish_state({
                    **state,
                    "status": "failed",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                })
                raise
            state.update({
                "status": "running",
                "started_at": datetime.now(UTC).isoformat(),
            })
            self._publish_state(state)
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            stdout_thread = threading.Thread(
                target=self._stream_pipe,
                args=(process.stdout, log_path, stdout_lines, "", self.redact_text),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._stream_pipe,
                args=(process.stderr, log_path, stderr_lines, "[stderr] ", self.redact_text),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            timed_out = False
            try:
                process.wait(timeout=safe_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_process_tree(process)
                process.wait()
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            with log_path.open("a", encoding="utf-8") as handle:
                if timed_out:
                    handle.write(f"\nTIMED OUT AFTER: {safe_timeout:g}s\n")
                handle.write(f"\nEXIT CODE: {process.returncode}\n")

        duration_ms = int((time.monotonic() - started) * 1000)
        self._publish_state({
            **state,
            "status": "timeout" if timed_out else ("success" if process.returncode == 0 else "failed"),
            "finished_at": datetime.now(UTC).isoformat(),
            "duration_ms": duration_ms,
            "exit_code": process.returncode,
        })
        return BlockingCommandResult(
            command=display_command,
            exit_code=process.returncode,
            timed_out=timed_out,
            timeout_seconds=safe_timeout,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            log_path=log_path,
            duration_ms=duration_ms,
            max_output_chars=self.max_output_chars,
        )

    def _publish_state(self, state: dict) -> None:
        if not self.state_observer:
            return
        try:
            self.state_observer(state)
        except Exception:
            LOGGER.exception("Could not publish command state")

    def _new_log_path(self) -> Path:
        command_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
        return self.log_dir / f"command_{command_id}.log"

    @staticmethod
    def _resolve_cwd(cwd: str | Path | None) -> str | None:
        if cwd is None:
            return None
        path = Path(cwd).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("cwd must be an existing directory")
        return str(path)

    @staticmethod
    def _stream_pipe(pipe, log_path: Path, lines: list[str], prefix: str, redact_text) -> None:
        for line in iter(pipe.readline, ""):
            safe_line = redact_text(line)
            lines.append(safe_line)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{prefix}{safe_line}")
        pipe.close()
