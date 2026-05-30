from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import (
    AGENT_STATUS_CANCELLED,
    AGENT_STATUS_COMPLETED,
    AGENT_STATUS_FAILED,
    AGENT_STATUS_QUEUED,
    AGENT_STATUS_RUNNING,
    AGENT_STATUS_STALE,
    AgentRecord,
    AgentSpec,
    TERMINAL_AGENT_STATUSES,
    redact_agent_payload,
)
from .store import AgentStore


class AgentManager:
    def __init__(
        self,
        storage_dir: str | Path,
        *,
        max_running_agents: int = 5,
        allow_parallel_same_cwd: bool = True,
        stale_after_seconds: int = 180,
        hard_timeout_seconds: int = 3600,
        default_wait_timeout_seconds: int = 10,
        default_agent_timeout_seconds: int | None = None,
        max_log_bytes: int = 10_000_000,
        cwd_allowlist: list[str] | None = None,
        enabled: bool = True,
    ):
        self.storage_dir = Path(storage_dir)
        self.src_dir = Path(__file__).resolve().parent.parent
        self.db_path = self.storage_dir / "agents.sqlite"
        self.store = AgentStore(self.db_path, self.storage_dir)
        self.max_running_agents = int(max_running_agents)
        self.allow_parallel_same_cwd = bool(allow_parallel_same_cwd)
        self.stale_after_seconds = int(stale_after_seconds)
        self.hard_timeout_seconds = int(hard_timeout_seconds)
        self.default_wait_timeout_seconds = int(default_wait_timeout_seconds)
        self.default_agent_timeout_seconds = default_agent_timeout_seconds
        self.max_log_bytes = int(max_log_bytes)
        self.cwd_allowlist = [Path(path).expanduser().resolve() for path in (cwd_allowlist or [])]
        self.enabled = bool(enabled)
        self._scheduler_started = False
        self._scheduler_stop = threading.Event()
        self._scheduler_lock = threading.Lock()

    @classmethod
    def from_settings(cls, base_dir: Path, settings: dict[str, Any]) -> "AgentManager":
        cfg = settings.get("agents") or {}
        storage_dir = Path(cfg.get("storage_dir", "data/agents"))
        if not storage_dir.is_absolute():
            storage_dir = base_dir / storage_dir
        return cls(
            storage_dir=storage_dir,
            max_running_agents=cfg.get("max_running_agents", 5),
            allow_parallel_same_cwd=cfg.get("allow_parallel_same_cwd", True),
            stale_after_seconds=cfg.get("stale_after_seconds", 180),
            hard_timeout_seconds=cfg.get("hard_timeout_seconds", 3600),
            default_wait_timeout_seconds=cfg.get("default_wait_timeout_seconds", 10),
            default_agent_timeout_seconds=cfg.get("default_agent_timeout_seconds"),
            max_log_bytes=cfg.get("max_log_bytes", 10_000_000),
            cwd_allowlist=cfg.get("cwd_allowlist") or [],
            enabled=cfg.get("enabled", True),
        )

    def submit(self, spec: AgentSpec, parent_id: str | None = None) -> dict[str, Any]:
        self._ensure_enabled()
        if not spec.prompt.strip():
            raise ValueError("prompt must not be empty")
        spec.cwd = self.resolve_cwd(spec.cwd)
        spec.wait_timeout_seconds = int(spec.wait_timeout_seconds or self.default_wait_timeout_seconds)
        if spec.agent_timeout_seconds is None:
            spec.agent_timeout_seconds = self.default_agent_timeout_seconds
        agent_id = self.new_agent_id()
        record = self.store.create_agent(agent_id, spec, parent_id=parent_id)
        return {
            "ok": True,
            "agent_id": agent_id,
            "status": record.status,
            "position": self.store.queue_position(agent_id),
            "max_running_agents": self.max_running_agents,
            "status_url": f"/agents/{agent_id}",
        }

    def get(self, agent_id: str, *, include_prompt: bool = True, include_result: bool = True) -> dict[str, Any]:
        record = self.require_agent(agent_id)
        payload = self.record_public_payload(record, include_prompt=include_prompt)
        response: dict[str, Any] = {"ok": True, "agent": payload}
        if include_result:
            response["result"] = self.store.read_json(agent_id, "result.json")
        return redact_agent_payload(response)

    def list(self, status: str | None = None, limit: int = 50, include_completed: bool = True) -> dict[str, Any]:
        records = self.store.list_agents(status=status, limit=limit, include_completed=include_completed)
        return {
            "ok": True,
            "agents": [self.record_public_payload(record, include_prompt=False) for record in records],
            "counts": self.store.count_by_status(),
            "max_running_agents": self.max_running_agents,
        }

    def logs(self, agent_id: str, stream: str = "stdout", tail: int = 200) -> dict[str, Any]:
        self.require_agent(agent_id)
        return {
            "ok": True,
            "agent_id": agent_id,
            "stream": stream,
            "tail": tail,
            "content": self.store.tail_log(agent_id, stream=stream, tail=tail, max_bytes=self.max_log_bytes),
        }

    def cancel(self, agent_id: str, *, force: bool = False) -> dict[str, Any]:
        record = self.require_agent(agent_id)
        if record.status in TERMINAL_AGENT_STATUSES:
            return {"ok": True, "agent_id": agent_id, "status": record.status, "already_terminal": True}
        if record.status == AGENT_STATUS_RUNNING and record.pid:
            self._terminate_pid(record.pid, force=force)
        self.store.update_status(agent_id, AGENT_STATUS_CANCELLED, completed=True)
        return {"ok": True, "agent_id": agent_id, "status": AGENT_STATUS_CANCELLED}

    def update(self, agent_id: str, **fields) -> dict[str, Any]:
        record = self.require_agent(agent_id)
        if record.status == AGENT_STATUS_RUNNING:
            raise RuntimeError("cannot update a running agent")
        fields = {key: value for key, value in fields.items() if value is not None}
        if "cwd" in fields:
            fields["cwd"] = self.resolve_cwd(fields["cwd"])
        updated = self.store.update_agent_fields(agent_id, fields)
        return {"ok": True, "agent": self.record_public_payload(updated, include_prompt=True)}

    def retry(self, agent_id: str, *, prompt_override: str | None = None, clone: bool = True, purpose: str | None = None) -> dict[str, Any]:
        record = self.require_agent(agent_id)
        prompt = prompt_override if prompt_override is not None else record.prompt
        spec = AgentSpec(
            prompt=prompt,
            provider=record.provider,
            purpose=purpose if purpose is not None else record.purpose,
            cwd=record.cwd,
            model=record.model,
            api_base=record.api_base,
            auto_run=record.auto_run,
            llm_supports_functions=record.llm_supports_functions,
            context_window=record.context_window,
            max_tokens=record.max_tokens,
            wait_timeout_seconds=record.wait_timeout_seconds,
            agent_timeout_seconds=record.agent_timeout_seconds,
            conversation_id=record.conversation_id,
            chatgpt_url=record.chatgpt_url,
            metadata={**record.metadata, "retry_of": agent_id},
        )
        parent_id = agent_id if clone else record.parent_id
        result = self.submit(spec, parent_id=parent_id)
        result["old_agent_id"] = agent_id
        result["new_agent_id"] = result["agent_id"]
        result["parent_id"] = parent_id
        return result

    def cleanup(self, older_than_days: int, statuses: list[str] | None = None, dry_run: bool = True) -> dict[str, Any]:
        return self.store.cleanup(older_than_days=older_than_days, statuses=statuses, dry_run=dry_run)

    def settings_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": self.enabled,
            "storage_dir": str(self.storage_dir),
            "db_path": str(self.db_path),
            "max_running_agents": self.max_running_agents,
            "allow_parallel_same_cwd": self.allow_parallel_same_cwd,
            "stale_after_seconds": self.stale_after_seconds,
            "hard_timeout_seconds": self.hard_timeout_seconds,
            "default_wait_timeout_seconds": self.default_wait_timeout_seconds,
            "default_agent_timeout_seconds": self.default_agent_timeout_seconds,
            "max_log_bytes": self.max_log_bytes,
            "cwd_allowlist": [str(path) for path in self.cwd_allowlist],
        }

    def recover(self):
        for record in self.store.list_agents(status=AGENT_STATUS_RUNNING, limit=500):
            self.store.update_status(record.agent_id, AGENT_STATUS_STALE, error="gateway_recovered_running_agent", completed=True)

    def start_scheduler_thread(self, interval_seconds: float = 2.0):
        if self._scheduler_started:
            return
        self._scheduler_started = True
        thread = threading.Thread(target=self._scheduler_loop, args=(interval_seconds,), daemon=True, name="agent-manager-scheduler")
        thread.start()

    def stop_scheduler_thread(self):
        self._scheduler_stop.set()

    def scheduler_tick(self):
        if not self.enabled:
            return
        with self._scheduler_lock:
            self.mark_dead_running_agents()
            self.mark_stale_running_agents()
            self.mark_hard_timed_out_agents()
            running = self.store.list_agents(status=AGENT_STATUS_RUNNING, limit=500)
            capacity = max(0, self.max_running_agents - len(running))
            if capacity <= 0:
                return
            running_cwds = {record.cwd for record in running if record.cwd}
            for record in self.store.next_queued(capacity):
                if not self.allow_parallel_same_cwd and record.cwd in running_cwds:
                    continue
                self.launch_record(record)
                if record.cwd:
                    running_cwds.add(record.cwd)

    def mark_dead_running_agents(self):
        for record in self.store.list_agents(status=AGENT_STATUS_RUNNING, limit=500):
            if record.pid and self._pid_exists(record.pid):
                continue
            error = "process_exited_without_status"
            stderr_tail = self.store.tail_log(record.agent_id, stream="stderr", tail=20, max_bytes=4000).strip()
            if stderr_tail:
                error = stderr_tail[-1000:]
            self.store.update_status(record.agent_id, AGENT_STATUS_FAILED, error=error, completed=True)

    def mark_stale_running_agents(self):
        now = datetime.now(UTC)
        for record in self.store.list_agents(status=AGENT_STATUS_RUNNING, limit=500):
            heartbeat_value = record.heartbeat_at or record.started_at
            if not heartbeat_value:
                continue
            heartbeat = datetime.fromisoformat(heartbeat_value)
            if (now - heartbeat).total_seconds() > self.stale_after_seconds:
                self.store.update_status(record.agent_id, AGENT_STATUS_STALE, error="heartbeat_stale", completed=True)

    def mark_hard_timed_out_agents(self):
        """Tue les agents qui dépassent hard_timeout_seconds depuis leur démarrage."""
        if self.hard_timeout_seconds <= 0:
            return
        now = datetime.now(UTC)
        for record in self.store.list_agents(status=AGENT_STATUS_RUNNING, limit=500):
            if not record.started_at:
                continue
            started = datetime.fromisoformat(record.started_at)
            elapsed = (now - started).total_seconds()
            if elapsed > self.hard_timeout_seconds:
                self._terminate_pid(record.pid, force=True) if record.pid else None
                self.store.update_status(
                    record.agent_id, AGENT_STATUS_TIMEOUT_HARD,
                    error=f"hard_timeout_{self.hard_timeout_seconds}s",
                    completed=True,
                )

    def launch_record(self, record: AgentRecord):
        stdout_path = self.store.run_dir(record.agent_id) / "stdout.log"
        stderr_path = self.store.run_dir(record.agent_id) / "stderr.log"
        stdout = open(stdout_path, "ab")
        stderr = open(stderr_path, "ab")
        cmd = [
            sys.executable,
            "-m",
            "agent_manager.runner",
            "--agent-id",
            record.agent_id,
            "--db",
            str(self.db_path),
            "--storage-dir",
            str(self.storage_dir),
        ]
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(self.src_dir)
            if not existing_pythonpath
            else str(self.src_dir) + os.pathsep + existing_pythonpath
        )
        process = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, cwd=record.cwd or None, close_fds=True, env=env)
        self.store.update_status(record.agent_id, AGENT_STATUS_RUNNING, pid=process.pid, heartbeat=True, started=True)

    def resolve_cwd(self, cwd: str | None) -> str:
        path = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
        if self.cwd_allowlist:
            allowed = any(path == root or root in path.parents for root in self.cwd_allowlist)
            if not allowed:
                raise ValueError(f"cwd is outside allowed paths: {path}")
        return str(path)

    def record_public_payload(self, record: AgentRecord, *, include_prompt: bool = True) -> dict[str, Any]:
        payload = asdict(record)
        if not include_prompt:
            payload.pop("prompt", None)
        payload.pop("chatgpt_url", None)
        return redact_agent_payload(payload)

    def require_agent(self, agent_id: str) -> AgentRecord:
        record = self.store.get_agent(agent_id)
        if record is None:
            raise KeyError(agent_id)
        return record

    def new_agent_id(self) -> str:
        return "agt_" + secrets.token_hex(8)

    def _ensure_enabled(self):
        if not self.enabled:
            raise RuntimeError("agents are disabled by config/settings.yaml")

    def _scheduler_loop(self, interval_seconds: float):
        while not self._scheduler_stop.wait(interval_seconds):
            try:
                self.scheduler_tick()
            except Exception as exc:
                self.store.append_event("scheduler", {"event": "scheduler_error", "error": str(exc)})

    def _terminate_pid(self, pid: int, *, force: bool = False):
        try:
            if force:
                os.kill(pid, 9)
            else:
                os.kill(pid, 15)
        except ProcessLookupError:
            return

    def _pid_exists(self, pid: int) -> bool:
        ps = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], check=False, capture_output=True, text=True)
        if ps.returncode != 0 or not ps.stdout.strip():
            return False
        if "Z" in ps.stdout.strip():
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
