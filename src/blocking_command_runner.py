from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from command_queue import process_group_options, terminate_process_tree


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
    def __init__(self, log_dir: Path, worker_limit: int = 4, max_output_chars: int = 50_000):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars
        self._capacity = threading.BoundedSemaphore(max(1, int(worker_limit)))

    def run(
        self,
        command: str,
        cwd: str | Path | None = None,
        timeout_seconds: float = 300,
    ) -> BlockingCommandResult:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        safe_timeout = max(0.1, min(float(timeout_seconds), 86_400.0))
        resolved_cwd = self._resolve_cwd(cwd)
        started = time.monotonic()
        with self._capacity:
            log_path = self._new_log_path()
            log_path.write_text(f"COMMAND:\n{command}\n\n", encoding="utf-8")
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
            stdout_lines: list[str] = []
            stderr_lines: list[str] = []
            stdout_thread = threading.Thread(
                target=self._stream_pipe,
                args=(process.stdout, log_path, stdout_lines, ""),
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=self._stream_pipe,
                args=(process.stderr, log_path, stderr_lines, "[stderr] "),
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

        return BlockingCommandResult(
            command=command,
            exit_code=process.returncode,
            timed_out=timed_out,
            timeout_seconds=safe_timeout,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            log_path=log_path,
            duration_ms=int((time.monotonic() - started) * 1000),
            max_output_chars=self.max_output_chars,
        )

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
    def _stream_pipe(pipe, log_path: Path, lines: list[str], prefix: str) -> None:
        for line in iter(pipe.readline, ""):
            lines.append(line)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{prefix}{line}")
        pipe.close()
