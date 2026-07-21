import json
import time

from blocking_command_runner import BlockingCommandRunner
from command_guard import SecretRedactor
from command_queue import CommandQueue


def test_blocking_runner_redacts_command_and_output(tmp_path):
    redactor = SecretRedactor(("sentinel-secret",))
    runner = BlockingCommandRunner(tmp_path, redact_text=redactor.redact_text)
    result = runner.run("printf sentinel-secret")
    assert "sentinel-secret" not in result.render()
    assert "sentinel-secret" not in result.log_path.read_text()


def test_realtime_queue_redacts_state_output_database_and_log(tmp_path):
    redactor = SecretRedactor(("sentinel-secret",))
    queue = CommandQueue(tmp_path / "queue.db", tmp_path / "logs", redact_text=redactor.redact_text)
    try:
        state = queue.enqueue("printf sentinel-secret")
        for _ in range(100):
            state = queue.get_state(state["execution_id"])
            if state["status"] in {"success", "failed"}:
                break
            time.sleep(0.02)
        page = queue.get_output(state["execution_id"])
        log = queue.get_log(state["execution_id"])["content_base64"]
        import base64
        rendered = repr(state) + repr(page) + base64.b64decode(log).decode()
        assert "sentinel-secret" not in rendered
        import sqlite3
        with sqlite3.connect(tmp_path / "queue.db") as connection:
            stored = connection.execute("SELECT command FROM executions").fetchone()[0]
        assert "sentinel-secret" not in stored
    finally:
        queue.close()


def test_gateway_denial_never_calls_runner(monkeypatch):
    import mcp_gateway

    called = []
    monkeypatch.setattr(mcp_gateway, "_run_command_blocking", lambda *a, **k: called.append(True))
    result = mcp_gateway.run_command("git reset --hard")
    assert result["status"] == "denied"
    assert result["remediation"]["commands"]
    assert called == []


def test_gateway_log_redacts_nested_secrets(tmp_path, monkeypatch):
    import mcp_gateway

    monkeypatch.setattr(mcp_gateway, "LOG_FILE", tmp_path / "gateway.log")
    monkeypatch.setattr(mcp_gateway, "SECRET_REDACTOR", SecretRedactor(("sentinel-secret",)))
    mcp_gateway.log_action("test", {"nested": ["sentinel-secret", "Authorization: Bearer abc"]})
    text = (tmp_path / "gateway.log").read_text()
    assert "sentinel-secret" not in text
    assert "Bearer abc" not in text


def test_every_retry_is_reinspected(monkeypatch):
    import mcp_gateway

    calls = []
    original = mcp_gateway.COMMAND_GUARD.inspect

    def inspect(request):
        calls.append(request.command)
        return original(request)

    monkeypatch.setattr(mcp_gateway.COMMAND_GUARD, "inspect", inspect)
    first = mcp_gateway.run_command("git reset --hard")
    second = mcp_gateway.run_command("git reset --hard")
    assert first["status"] == second["status"] == "denied"
    assert calls == ["git reset --hard", "git reset --hard"]


def test_redacted_queue_resumes_encrypted_payload_after_restart(tmp_path):
    database = tmp_path / "queue.db"
    logs = tmp_path / "logs"
    redactor = SecretRedactor(("sentinel-secret",))
    queue = CommandQueue(database, logs, worker_limit=0, redact_text=redactor.redact_text)
    state = queue.enqueue("printf sentinel-secret")
    queue.close()

    restarted = CommandQueue(database, logs, worker_limit=1, redact_text=redactor.redact_text)
    try:
        assert restarted.queue_state()["recovery_required"] is True
        restarted.resolve_recovery("resume")
        for _ in range(100):
            final = restarted.get_state(state["execution_id"])
            if final["status"] in {"success", "failed"}:
                break
            time.sleep(0.02)
        assert final["status"] == "success"
        assert "sentinel-secret" not in repr(final)
    finally:
        restarted.close()

def test_queue_late_denial_keeps_structured_remediation(tmp_path):
    from command_guard import BuiltinGuardProvider, GuardRequest
    queue = CommandQueue(
        tmp_path / "queue.db",
        tmp_path / "logs",
        inspect_command=lambda command, cwd: BuiltinGuardProvider().inspect(GuardRequest("run_command", {}, command, cwd)),
    )
    try:
        state = queue.enqueue("git reset --hard")
        for _ in range(100):
            state = queue.get_state(state["execution_id"])
            if state["status"] == "cancelled":
                break
            time.sleep(0.02)
        assert state["status"] == "cancelled"
        payload = json.loads(state["last_line"])
        assert payload["status"] == "denied"
        assert payload["remediation"]["commands"]
    finally:
        queue.close()
