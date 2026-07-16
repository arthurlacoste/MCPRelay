from __future__ import annotations

import base64
import codecs
import json
import os
import secrets
import signal
import sqlite3
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

TERMINAL_STATUSES = {'success', 'failed', 'cancelled', 'timeout', 'interrupted'}
ACTIVE_STATUSES = {'starting', 'running'}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def process_group_options() -> dict:
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def terminate_process_tree(process: subprocess.Popen, grace_seconds: float = 1.0) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            capture_output=True,
            text=True,
            check=False,
        )
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class StreamParser:
    def __init__(self, emit: Callable[[str, bool], None], max_buffer_chars: int = 65_536):
        self.emit = emit
        self.max_buffer_chars = max(1024, max_buffer_chars)
        self.buffer = ''
        self.after_cr = False
        self.decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

    def feed(self, chunk: bytes) -> None:
        text = self.decoder.decode(chunk)
        for character in text:
            if character == '\r':
                self.emit(self.buffer, self.after_cr)
                self.buffer = ''
                self.after_cr = True
            elif character == '\n':
                if self.buffer or not self.after_cr:
                    self.emit(self.buffer, self.after_cr)
                self.buffer = ''
                self.after_cr = False
            else:
                self.buffer += character
                if len(self.buffer) >= self.max_buffer_chars:
                    self.emit(self.buffer, self.after_cr)
                    self.buffer = ''
                    self.after_cr = False

    def finish(self) -> None:
        self.buffer += self.decoder.decode(b'', final=True)
        if self.buffer:
            self.emit(self.buffer, self.after_cr)
        self.buffer = ''


class CommandQueue:
    def __init__(
        self,
        database_path: Path,
        log_dir: Path,
        worker_limit: int = 4,
        max_lines_per_execution: int = 20_000,
        history_limit: int = 2_000,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        self.database_path = Path(database_path)
        self.log_dir = Path(log_dir)
        self.worker_limit = max(0, int(worker_limit))
        self.max_lines = max(100, int(max_lines_per_execution))
        self.history_limit = max(10, int(history_limit))
        self.on_event = on_event
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancelled: set[str] = set()
        self._closed = False
        self._initialize()
        self._recover_database()
        self._dispatch()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA foreign_keys=ON')
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    command TEXT NOT NULL,
                    cwd TEXT,
                    timeout_seconds REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    pid INTEGER,
                    exit_code INTEGER,
                    last_line TEXT,
                    last_stream TEXT,
                    line_count INTEGER NOT NULL DEFAULT 0,
                    truncated INTEGER NOT NULL DEFAULT 0,
                    log_path TEXT NOT NULL,
                    conversation_id TEXT,
                    purpose TEXT,
                    include_output INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS output_lines (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    execution_id TEXT NOT NULL,
                    stream TEXT NOT NULL,
                    text TEXT NOT NULL,
                    replace_line INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(execution_id) REFERENCES executions(execution_id)
                );
                CREATE INDEX IF NOT EXISTS output_execution_cursor
                    ON output_lines(execution_id, cursor);
                CREATE TABLE IF NOT EXISTS queue_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            ''')

    def _recover_database(self) -> None:
        with self._connect() as connection:
            active = connection.execute(
                "SELECT COUNT(*) FROM executions WHERE status IN ('starting', 'running')"
            ).fetchone()[0]
            queued = connection.execute(
                "SELECT COUNT(*) FROM executions WHERE status = 'queued'"
            ).fetchone()[0]
            if active:
                rows = connection.execute(
                    "SELECT pid FROM executions WHERE status IN ('starting', 'running') AND pid IS NOT NULL"
                ).fetchall()
                for row in rows:
                    self._terminate_recovered_pid(row['pid'])
                connection.execute(
                    "UPDATE executions SET status = 'interrupted', finished_at = ?, pid = NULL "
                    "WHERE status IN ('starting', 'running')",
                    (utc_now(),),
                )
            if queued:
                connection.execute("UPDATE executions SET status = 'waiting' WHERE status = 'queued'")
            if active or queued:
                connection.execute(
                    "INSERT OR REPLACE INTO queue_meta(key, value) VALUES('recovery_required', '1')"
                )
                self._audit(connection, 'startup_recovery_required', {'active': active, 'queued': queued})
            else:
                connection.execute(
                    "INSERT OR IGNORE INTO queue_meta(key, value) VALUES('recovery_required', '0')"
                )

    def _terminate_recovered_pid(self, pid: int) -> None:
        if pid <= 0:
            return
        if os.name == 'nt':
            subprocess.run(
                ['taskkill', '/PID', str(pid), '/T', '/F'],
                capture_output=True,
                text=True,
                check=False,
            )
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return

    def enqueue(
        self,
        command: str,
        cwd: str | None = None,
        timeout_seconds: float = 300,
        conversation_id: str | None = None,
        purpose: str | None = None,
        include_output: bool = False,
    ) -> dict:
        if not isinstance(command, str) or not command.strip():
            raise ValueError('command must be a non-empty string')
        safe_timeout = max(0.1, min(float(timeout_seconds), 86_400.0))
        resolved_cwd = None
        if cwd:
            path = Path(cwd).expanduser().resolve()
            if not path.is_dir():
                raise ValueError('cwd must be an existing directory')
            resolved_cwd = str(path)
        execution_id = f'exec_{secrets.token_hex(8)}'
        log_path = self.log_dir / f'{execution_id}.log'
        with log_path.open('w', encoding='utf-8') as handle:
            handle.write(f'COMMAND:\n{command}\n\n')
        with self._connect() as connection:
            recovery = self._recovery_required(connection)
            status = 'waiting' if recovery else 'queued'
            connection.execute(
                'INSERT INTO executions(execution_id,status,command,cwd,timeout_seconds,created_at,'
                'log_path,conversation_id,purpose,include_output) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (execution_id, status, command, resolved_cwd, safe_timeout, utc_now(), str(log_path),
                 conversation_id, purpose, int(include_output)),
            )
            self._audit(connection, 'command_enqueued', {'execution_id': execution_id, 'status': status})
        result = self.get_state(execution_id, include_lines=False)
        self._dispatch()
        return result

    def _dispatch(self) -> None:
        with self._lock:
            if self._closed or self.worker_limit == 0:
                return
            with self._connect() as connection:
                if self._recovery_required(connection):
                    return
                active = connection.execute(
                    "SELECT COUNT(*) FROM executions WHERE status IN ('starting', 'running')"
                ).fetchone()[0]
                slots = self.worker_limit - active
                rows = connection.execute(
                    "SELECT execution_id FROM executions WHERE status = 'queued' ORDER BY created_at LIMIT ?",
                    (max(0, slots),),
                ).fetchall()
                for row in rows:
                    execution_id = row['execution_id']
                    changed = connection.execute(
                        "UPDATE executions SET status = 'starting' WHERE execution_id = ? AND status = 'queued'",
                        (execution_id,),
                    ).rowcount
                    if changed:
                        thread = threading.Thread(target=self._run, args=(execution_id,), daemon=True)
                        self._threads[execution_id] = thread
                        thread.start()

    def _run(self, execution_id: str) -> None:
        with self._connect() as connection:
            job = connection.execute(
                'SELECT * FROM executions WHERE execution_id = ?', (execution_id,)
            ).fetchone()
        if not job:
            return
        try:
            process = subprocess.Popen(
                job['command'], shell=True, cwd=job['cwd'], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0, **process_group_options(),
            )
        except Exception as error:
            self._finish(execution_id, 'failed', None, system_line=str(error))
            return
        with self._lock:
            self._processes[execution_id] = process
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE executions SET status='running', started_at=?, pid=? "
                "WHERE execution_id=? AND status='starting'",
                (utc_now(), process.pid, execution_id),
            ).rowcount
        if not changed:
            terminate_process_tree(process)
            return
        readers = [
            threading.Thread(target=self._read_pipe, args=(execution_id, 'stdout', process.stdout), daemon=True),
            threading.Thread(target=self._read_pipe, args=(execution_id, 'stderr', process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            process.wait(timeout=job['timeout_seconds'])
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_process_tree(process)
            process.wait()
        for reader in readers:
            reader.join(timeout=2)
        with self._connect() as connection:
            current = connection.execute(
                'SELECT status FROM executions WHERE execution_id=?', (execution_id,)
            ).fetchone()['status']
        if current == 'cancelled' or execution_id in self._cancelled:
            status = 'cancelled'
        elif timed_out:
            status = 'timeout'
        elif process.returncode == 0:
            status = 'success'
        else:
            status = 'failed'
        self._finish(execution_id, status, process.returncode)

    def _read_pipe(self, execution_id: str, stream: str, pipe) -> None:
        parser = StreamParser(lambda text, replace: self._append_line(execution_id, stream, text, replace))
        try:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    break
                parser.feed(chunk)
            parser.finish()
        finally:
            pipe.close()

    def _append_line(self, execution_id: str, stream: str, text: str, replace: bool = False) -> None:
        with self._lock:
            now = utc_now()
            with self._connect() as connection:
                connection.execute(
                    'INSERT INTO output_lines(execution_id,stream,text,replace_line,created_at) VALUES(?,?,?,?,?)',
                    (execution_id, stream, text, int(replace), now),
                )
                connection.execute(
                    'UPDATE executions SET last_line=?,last_stream=?,line_count=line_count+1 '
                    'WHERE execution_id=?', (text, stream, execution_id),
                )
                count = connection.execute(
                    'SELECT COUNT(*) FROM output_lines WHERE execution_id=?', (execution_id,)
                ).fetchone()[0]
                if count > self.max_lines:
                    remove = count - self.max_lines
                    connection.execute(
                        'DELETE FROM output_lines WHERE cursor IN (SELECT cursor FROM output_lines '
                        'WHERE execution_id=? ORDER BY cursor LIMIT ?)', (execution_id, remove),
                    )
                    connection.execute(
                        'UPDATE executions SET truncated=1 WHERE execution_id=?', (execution_id,)
                    )
                log_path = connection.execute(
                    'SELECT log_path FROM executions WHERE execution_id=?', (execution_id,)
                ).fetchone()['log_path']
            prefix = '[stderr] ' if stream == 'stderr' else ''
            with open(log_path, 'a', encoding='utf-8') as handle:
                handle.write(f'{prefix}{text}\n')

    def _finish(self, execution_id: str, status: str, exit_code: int | None, system_line: str | None = None) -> None:
        if system_line:
            self._append_line(execution_id, 'system', system_line)
        with self._lock:
            self._processes.pop(execution_id, None)
            self._cancelled.discard(execution_id)
            with self._connect() as connection:
                connection.execute(
                    'UPDATE executions SET status=?,exit_code=?,finished_at=?,pid=NULL WHERE execution_id=?',
                    (status, exit_code, utc_now(), execution_id),
                )
                job = connection.execute(
                    'SELECT log_path,line_count,conversation_id,purpose,include_output FROM executions '
                    'WHERE execution_id=?', (execution_id,)
                ).fetchone()
                self._audit(connection, 'command_finished', {
                    'execution_id': execution_id, 'status': status, 'exit_code': exit_code,
                })
            with open(job['log_path'], 'a', encoding='utf-8') as handle:
                handle.write(f'\nSTATUS: {status.upper()}\nEXIT CODE: {exit_code}\n')
        try:
            if self.on_event:
                event = self.get_state(execution_id, include_lines=False)
                event.update({
                    'conversation_id': job['conversation_id'],
                    'purpose': job['purpose'],
                    'include_output': bool(job['include_output']),
                })
                self.on_event(execution_id, event)
        except Exception:
            pass
        finally:
            self._dispatch()

    def stop(self, execution_id: str) -> dict:
        notify = False
        with self._lock:
            with self._connect() as connection:
                row = self._get_job(connection, execution_id)
                if row['status'] in TERMINAL_STATUSES:
                    return self._serialize(row)
                if row['status'] in {'queued', 'waiting'}:
                    connection.execute(
                        "UPDATE executions SET status='cancelled',finished_at=? WHERE execution_id=?",
                        (utc_now(), execution_id),
                    )
                    with open(row['log_path'], 'a', encoding='utf-8') as handle:
                        handle.write('\nSTATUS: CANCELLED\nEXIT CODE: None\n')
                    notify = True
                else:
                    self._cancelled.add(execution_id)
                    connection.execute(
                        "UPDATE executions SET status='cancelled',finished_at=? WHERE execution_id=?",
                        (utc_now(), execution_id),
                    )
                    process = self._processes.get(execution_id)
                    if process:
                        terminate_process_tree(process)
                self._audit(connection, 'command_stopped', {'execution_id': execution_id})
        state = self.get_state(execution_id, include_lines=False)
        if notify and self.on_event:
            event = {**state, 'conversation_id': row['conversation_id'], 'purpose': row['purpose'],
                     'include_output': bool(row['include_output'])}
            try:
                self.on_event(execution_id, event)
            except Exception:
                pass
        self._dispatch()
        return state

    def get_state(self, execution_id: str, after_cursor: int = 0, limit: int = 200, include_lines: bool = True) -> dict:
        with self._connect() as connection:
            row = self._get_job(connection, execution_id)
            result = self._serialize(row)
            if include_lines:
                result.update(self._page(connection, execution_id, after_cursor, limit))
            return result

    def get_output(self, execution_id: str, after_cursor: int = 0, limit: int = 500) -> dict:
        with self._connect() as connection:
            row = self._get_job(connection, execution_id)
            return {
                'execution_id': execution_id,
                'log_ref': f'logs/commands/{Path(row["log_path"]).name}',
                'truncated': bool(row['truncated']),
                **self._page(connection, execution_id, after_cursor, limit),
            }

    def get_log(self, execution_id: str, offset: int = 0, limit_bytes: int = 262_144) -> dict:
        with self._connect() as connection:
            row = self._get_job(connection, execution_id)
        safe_offset = max(0, int(offset))
        safe_limit = max(1024, min(int(limit_bytes), 1_048_576))
        log_path = Path(row['log_path'])
        try:
            file_size = log_path.stat().st_size
            with log_path.open('rb') as handle:
                handle.seek(min(safe_offset, file_size))
                content = handle.read(safe_limit)
        except OSError as error:
            raise ValueError(f'command log unavailable: {execution_id}') from error
        next_offset = min(safe_offset, file_size) + len(content)
        return {
            'execution_id': execution_id,
            'offset': next_offset,
            'has_more': next_offset < file_size,
            'content_base64': base64.b64encode(content).decode('ascii'),
            'size_bytes': file_size,
            'log_ref': f'logs/commands/{log_path.name}',
        }

    def queue_state(self, visible_limit: int = 8) -> dict:
        with self._connect() as connection:
            counts = {row['status']: row['count'] for row in connection.execute(
                'SELECT status,COUNT(*) AS count FROM executions GROUP BY status'
            )}
            rows = connection.execute(
                "SELECT * FROM executions ORDER BY CASE WHEN status IN ('running','starting') THEN 0 "
                "WHEN status IN ('queued','waiting') THEN 1 WHEN status IN ('failed','timeout','interrupted') "
                "THEN 2 ELSE 3 END, created_at DESC LIMIT ?", (max(1, min(int(visible_limit), 50)),),
            ).fetchall()
            active = sum(counts.get(status, 0) for status in ACTIVE_STATUSES)
            return {
                'workers': {'active': active, 'limit': self.worker_limit},
                'queued': counts.get('queued', 0) + counts.get('waiting', 0),
                'failed': counts.get('failed', 0) + counts.get('timeout', 0),
                'completed': counts.get('success', 0),
                'recovery_required': self._recovery_required(connection),
                'commands': [self._serialize(row) for row in rows],
            }

    def resolve_recovery(self, action: str) -> dict:
        if action not in {'resume', 'clear'}:
            raise ValueError("action must be 'resume' or 'clear'")
        with self._lock, self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if not self._recovery_required(connection):
                connection.rollback()
                return self.queue_state()
            if action == 'resume':
                connection.execute("UPDATE executions SET status='queued' WHERE status='waiting'")
            else:
                connection.execute(
                    "UPDATE executions SET status='cancelled',finished_at=? WHERE status='waiting'", (utc_now(),)
                )
            connection.execute(
                "INSERT OR REPLACE INTO queue_meta(key,value) VALUES('recovery_required','0')"
            )
            self._audit(connection, 'recovery_resolved', {'action': action})
            connection.commit()
        self._dispatch()
        return self.queue_state()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            processes = list(self._processes.values())
            threads = list(self._threads.values())
        for process in processes:
            terminate_process_tree(process)
        current = threading.current_thread()
        for thread in threads:
            if thread is not current:
                thread.join()

    def _get_job(self, connection: sqlite3.Connection, execution_id: str) -> sqlite3.Row:
        row = connection.execute(
            'SELECT * FROM executions WHERE execution_id=?', (execution_id,)
        ).fetchone()
        if not row:
            raise ValueError(f'unknown execution_id: {execution_id}')
        return row

    def _serialize(self, row: sqlite3.Row) -> dict:
        start = row['started_at'] or row['created_at']
        end = row['finished_at'] or utc_now()
        try:
            duration = max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() * 1000))
        except ValueError:
            duration = 0
        return {
            'execution_id': row['execution_id'], 'status': row['status'], 'command': row['command'],
            'cwd': row['cwd'], 'pid': row['pid'], 'created_at': row['created_at'],
            'started_at': row['started_at'], 'finished_at': row['finished_at'],
            'duration_ms': duration, 'exit_code': row['exit_code'], 'last_line': row['last_line'],
            'last_stream': row['last_stream'], 'line_count': row['line_count'],
            'truncated': bool(row['truncated']), 'log_ref': f'logs/commands/{Path(row["log_path"]).name}',
        }

    def _page(self, connection: sqlite3.Connection, execution_id: str, after_cursor: int, limit: int) -> dict:
        safe_limit = max(1, min(int(limit), 1000))
        rows = connection.execute(
            'SELECT * FROM output_lines WHERE execution_id=? AND cursor>? ORDER BY cursor LIMIT ?',
            (execution_id, max(0, int(after_cursor)), safe_limit + 1),
        ).fetchall()
        has_more = len(rows) > safe_limit
        rows = rows[:safe_limit]
        cursor = rows[-1]['cursor'] if rows else max(0, int(after_cursor))
        return {
            'cursor': cursor, 'has_more': has_more,
            'lines': [
                {'cursor': row['cursor'], 'stream': row['stream'], 'text': row['text'],
                 'replace': bool(row['replace_line']), 'created_at': row['created_at']}
                for row in rows
            ],
        }

    def _recovery_required(self, connection: sqlite3.Connection) -> bool:
        row = connection.execute("SELECT value FROM queue_meta WHERE key='recovery_required'").fetchone()
        return bool(row and row['value'] == '1')

    def _audit(self, connection: sqlite3.Connection, event: str, payload: dict) -> None:
        connection.execute(
            'INSERT INTO queue_audit(event,payload,created_at) VALUES(?,?,?)',
            (event, json.dumps(payload, ensure_ascii=False), utc_now()),
        )
        connection.execute(
            'DELETE FROM queue_audit WHERE id NOT IN (SELECT id FROM queue_audit ORDER BY id DESC LIMIT ?)',
            (self.history_limit * 4,),
        )
        stale = connection.execute(
            "SELECT execution_id,log_path FROM executions WHERE status IN "
            "('success','failed','cancelled','timeout','interrupted') ORDER BY finished_at DESC LIMIT -1 OFFSET ?",
            (self.history_limit,),
        ).fetchall()
        if stale:
            ids = [row['execution_id'] for row in stale]
            connection.executemany('DELETE FROM output_lines WHERE execution_id=?', ((item,) for item in ids))
            connection.executemany('DELETE FROM executions WHERE execution_id=?', ((item,) for item in ids))
            for row in stale:
                try:
                    Path(row['log_path']).unlink(missing_ok=True)
                except OSError:
                    pass
