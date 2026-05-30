from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import AgentRecord, AgentSpec, AGENT_STATUS_QUEUED, redact_agent_payload


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AgentStore:
    def __init__(self, db_path: str | Path, storage_dir: str | Path):
        self.db_path = Path(db_path)
        self.storage_dir = Path(storage_dir)
        self.runs_dir = self.storage_dir / "runs"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self):
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    purpose TEXT,
                    cwd TEXT,
                    model TEXT,
                    api_base TEXT,
                    auto_run INTEGER NOT NULL,
                    llm_supports_functions INTEGER NOT NULL,
                    context_window INTEGER NOT NULL,
                    max_tokens INTEGER NOT NULL,
                    wait_timeout_seconds INTEGER NOT NULL,
                    agent_timeout_seconds INTEGER,
                    conversation_id TEXT,
                    chatgpt_url TEXT,
                    parent_id TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    heartbeat_at TEXT,
                    pid INTEGER,
                    exit_code INTEGER,
                    error TEXT
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
            if "provider" not in columns:
                conn.execute("ALTER TABLE agents ADD COLUMN provider TEXT NOT NULL DEFAULT 'deepseek'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_status_updated ON agents(status, updated_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_id)")

    def run_dir(self, agent_id: str) -> Path:
        path = self.runs_dir / agent_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create_agent(self, agent_id: str, spec: AgentSpec, parent_id: str | None = None) -> AgentRecord:
        now = utc_now()
        metadata_json = json.dumps(redact_agent_payload(spec.metadata), ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, status, prompt, provider, purpose, cwd, model, api_base, auto_run,
                    llm_supports_functions, context_window, max_tokens, wait_timeout_seconds,
                    agent_timeout_seconds, conversation_id, chatgpt_url, parent_id, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    AGENT_STATUS_QUEUED,
                    spec.prompt,
                    spec.provider,
                    spec.purpose,
                    spec.cwd,
                    spec.model,
                    spec.api_base,
                    int(spec.auto_run),
                    int(spec.llm_supports_functions),
                    int(spec.context_window),
                    int(spec.max_tokens),
                    int(spec.wait_timeout_seconds),
                    spec.agent_timeout_seconds,
                    spec.conversation_id,
                    spec.chatgpt_url,
                    parent_id,
                    metadata_json,
                    now,
                    now,
                ),
            )
        self.write_json(agent_id, "input.json", self.spec_to_payload(spec, parent_id=parent_id))
        self.append_event(agent_id, {"event": "created", "status": AGENT_STATUS_QUEUED})
        record = self.get_agent(agent_id)
        assert record is not None
        return record

    def spec_to_payload(self, spec: AgentSpec, parent_id: str | None = None) -> dict[str, Any]:
        payload = asdict(spec)
        payload["parent_id"] = parent_id
        return redact_agent_payload(payload)

    def row_to_record(self, row: sqlite3.Row) -> AgentRecord:
        return AgentRecord(
            agent_id=row["agent_id"],
            status=row["status"],
            prompt=row["prompt"],
            provider=row["provider"] or "deepseek",
            purpose=row["purpose"],
            cwd=row["cwd"],
            model=row["model"],
            api_base=row["api_base"],
            auto_run=bool(row["auto_run"]),
            llm_supports_functions=bool(row["llm_supports_functions"]),
            context_window=row["context_window"],
            max_tokens=row["max_tokens"],
            wait_timeout_seconds=row["wait_timeout_seconds"],
            agent_timeout_seconds=row["agent_timeout_seconds"],
            conversation_id=row["conversation_id"],
            chatgpt_url=row["chatgpt_url"],
            parent_id=row["parent_id"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            heartbeat_at=row["heartbeat_at"],
            pid=row["pid"],
            exit_code=row["exit_code"],
            error=row["error"],
        )

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return self.row_to_record(row) if row else None

    def list_agents(self, status: str | None = None, limit: int = 50, include_completed: bool = True) -> list[AgentRecord]:
        limit = max(1, min(int(limit), 500))
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        elif not include_completed:
            clauses.append("status != 'completed'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM agents {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self.row_to_record(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM agents GROUP BY status").fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def update_status(
        self,
        agent_id: str,
        status: str,
        *,
        pid: int | None = None,
        exit_code: int | None = None,
        error: str | None = None,
        heartbeat: bool = False,
        started: bool = False,
        completed: bool = False,
    ):
        now = utc_now()
        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]
        if pid is not None:
            assignments.append("pid = ?")
            params.append(pid)
        if exit_code is not None:
            assignments.append("exit_code = ?")
            params.append(exit_code)
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        if heartbeat:
            assignments.append("heartbeat_at = ?")
            params.append(now)
        if started:
            assignments.append("started_at = ?")
            params.append(now)
        if completed:
            assignments.append("completed_at = ?")
            params.append(now)
        params.append(agent_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE agents SET {', '.join(assignments)} WHERE agent_id = ?", params)
        self.append_event(agent_id, {"event": "status", "status": status, "pid": pid, "exit_code": exit_code, "error": error})

    def update_agent_fields(self, agent_id: str, fields: dict[str, Any]) -> AgentRecord:
        allowed = {
            "prompt", "provider", "purpose", "cwd", "model", "api_base", "context_window",
            "max_tokens", "wait_timeout_seconds", "agent_timeout_seconds",
            "metadata_json",
        }
        assignments = []
        params = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            params.append(json.dumps(redact_agent_payload(value), ensure_ascii=False) if key == "metadata_json" else value)
        if assignments:
            assignments.append("updated_at = ?")
            params.append(utc_now())
            params.append(agent_id)
            with self.connect() as conn:
                conn.execute(f"UPDATE agents SET {', '.join(assignments)} WHERE agent_id = ?", params)
            self.append_event(agent_id, {"event": "updated", "fields": sorted(fields.keys())})
            record = self.get_agent(agent_id)
            if record:
                self.write_json(agent_id, "input.json", self.record_to_input_payload(record))
        record = self.get_agent(agent_id)
        if record is None:
            raise KeyError(agent_id)
        return record

    def record_to_input_payload(self, record: AgentRecord) -> dict[str, Any]:
        return redact_agent_payload(asdict(record))

    def next_queued(self, limit: int) -> list[AgentRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE status = ? ORDER BY created_at ASC LIMIT ?",
                (AGENT_STATUS_QUEUED, max(0, int(limit))),
            ).fetchall()
        return [self.row_to_record(row) for row in rows]

    def queue_position(self, agent_id: str) -> int | None:
        record = self.get_agent(agent_id)
        if not record or record.status != AGENT_STATUS_QUEUED:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) + 1 AS position FROM agents WHERE status = ? AND created_at < ?",
                (AGENT_STATUS_QUEUED, record.created_at),
            ).fetchone()
        return int(row["position"])

    def write_json(self, agent_id: str, filename: str, payload: Any):
        path = self.run_dir(agent_id) / filename
        path.write_text(json.dumps(redact_agent_payload(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(self, agent_id: str, filename: str) -> Any | None:
        path = self.run_dir(agent_id) / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_event(self, agent_id: str, payload: dict[str, Any]):
        path = self.run_dir(agent_id) / "events.jsonl"
        entry = {"timestamp": utc_now(), **redact_agent_payload(payload)}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def tail_log(self, agent_id: str, stream: str = "stdout", tail: int = 200, max_bytes: int | None = None) -> str:
        if stream not in {"stdout", "stderr", "events"}:
            raise ValueError("stream must be one of: stdout, stderr, events")
        filename = "events.jsonl" if stream == "events" else f"{stream}.log"
        path = self.run_dir(agent_id) / filename
        if not path.exists():
            return ""
        data = path.read_bytes()
        if max_bytes and len(data) > max_bytes:
            data = data[-max_bytes:]
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[-max(1, int(tail)):])

    def cleanup(self, older_than_days: int, statuses: list[str] | None = None, dry_run: bool = True) -> dict[str, Any]:
        cutoff = (datetime.now(UTC) - timedelta(days=max(0, int(older_than_days)))).isoformat()
        params: list[Any] = [cutoff]
        clauses = ["updated_at < ?"]
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(f"SELECT agent_id FROM agents WHERE {where}", params).fetchall()
            agent_ids = [row["agent_id"] for row in rows]
            if not dry_run and agent_ids:
                conn.executemany("DELETE FROM agents WHERE agent_id = ?", [(agent_id,) for agent_id in agent_ids])
        if not dry_run:
            for agent_id in agent_ids:
                shutil.rmtree(self.runs_dir / agent_id, ignore_errors=True)
        return {"ok": True, "dry_run": dry_run, "count": len(agent_ids), "agent_ids": agent_ids}
