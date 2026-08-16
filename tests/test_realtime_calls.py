import os
import time
from pathlib import Path
from datetime import UTC, datetime, timedelta

from src.realtime_calls import RealtimeCallStore, format_age, read_call_log, shorten
from src.secret_redactor import SecretRedactor


def call(execution_id, status, created_at, command="echo ok", purpose=None):
    return {
        "execution_id": execution_id,
        "status": status,
        "created_at": created_at,
        "started_at": created_at if status != "queued" else None,
        "finished_at": created_at if status in {"success", "failed"} else None,
        "duration_ms": 2000,
        "command": command,
        "purpose": purpose,
    }


def test_store_sorts_active_queued_then_terminal_calls_by_datetime():
    store = RealtimeCallStore()
    base = datetime(2026, 7, 22, tzinfo=UTC)
    store.update(call("error", "failed", (base + timedelta(seconds=1)).isoformat()))
    store.update(call("done", "success", (base + timedelta(seconds=2)).isoformat()))
    store.update(call("queued", "queued", (base + timedelta(seconds=3)).isoformat()))
    store.update(call("running", "running", (base + timedelta(seconds=4)).isoformat()))

    assert [item["execution_id"] for item in store.snapshot()["calls"]] == [
        "running", "queued", "done", "error",
    ]


def test_store_sorts_missing_timestamps_last_within_status_group():
    store = RealtimeCallStore()
    base = datetime(2026, 7, 22, tzinfo=UTC)
    store.update(call("dated", "success", base.isoformat()))
    store.update(call("undated", "success", None))

    assert [item["execution_id"] for item in store.snapshot()["calls"]] == [
        "dated", "undated",
    ]


def test_store_masks_secrets_and_terminal_controls_in_display_fields():
    redactor = SecretRedactor(("top-secret-value",))
    store = RealtimeCallStore(redact_text=redactor.redact_text)
    store.update(call(
        "secret", "running", datetime.now(UTC).isoformat(),
        command="curl\n\x1b]52;c;clipboard\x07-H 'Authorization: Bearer top-secret-value' --api-key=abc123",
        purpose="Deploy top-secret-value\x1b[2J",
    ))

    item = store.snapshot()["calls"][0]
    preview = item["preview"]
    assert "top-secret-value" not in preview
    assert "abc123" not in preview
    assert "[REDACTED]" in preview
    assert "\n" not in preview
    assert "\x1b" not in preview
    assert "top-secret-value" not in item["purpose"]
    assert "\x1b" not in item["purpose"]


def test_store_redacts_and_bounds_generic_payload_and_result():
    redactor = SecretRedactor(("top-secret-value",))
    store = RealtimeCallStore(redact_text=redactor.redact_text)
    activity_id = store.start_activity(
        tool="skills_search",
        payload={"query": "top-secret-value", "extra": "x" * 40_000},
        fields={"query": "top-secret-value"},
    )
    store.finish_activity(activity_id, result={"token": "top-secret-value", "ok": True})

    item = store.snapshot()["calls"][0]
    assert "top-secret-value" not in item["payload"]
    assert "top-secret-value" not in item["result"]
    assert "top-secret-value" not in repr(item["fields"])
    assert len(item["payload"]) == 32_000


def test_unserializable_activity_data_does_not_break_store(caplog):
    class BrokenPayload:
        def model_dump(self, *, mode):
            raise RuntimeError("serialization failed")

    store = RealtimeCallStore()
    store.update({
        "execution_id": "safe-observer",
        "status": "success",
        "payload": BrokenPayload(),
        "result": BrokenPayload(),
    })

    item = store.snapshot()["calls"][0]
    assert item["payload"] == ""
    assert item["result"] == ""
    assert "serialization failed" in caplog.text


def test_recent_buffer_is_bounded_but_active_calls_remain():
    store = RealtimeCallStore(max_entries=2)
    now = datetime.now(UTC).isoformat()
    store.update(call("running", "running", now))
    for index in range(3):
        store.update(call(f"done-{index}", "success", now))

    ids = [item["execution_id"] for item in store.snapshot()["calls"]]
    assert ids[0] == "running"
    assert set(ids[1:]) == {"done-1", "done-2"}


def test_queued_calls_are_bounded_but_running_calls_remain():
    store = RealtimeCallStore(max_entries=2)
    now = datetime.now(UTC)
    store.update(call("running", "running", now.isoformat()))
    for index in range(3):
        store.update(call(f"queued-{index}", "queued", (now + timedelta(seconds=index)).isoformat()))

    ids = [item["execution_id"] for item in store.snapshot()["calls"]]
    assert ids == ["running", "queued-2"]


def test_snapshot_is_private_and_display_values_are_bounded(tmp_path):
    path = tmp_path / "realtime_calls.json"
    store = RealtimeCallStore(snapshot_path=path)
    assert path.exists()
    assert store.snapshot()["calls"] == []
    store.update(call(
        "bounded", "running", datetime.now(UTC).isoformat(),
        command="x" * 2_000,
        purpose="y" * 1_000,
    ))

    item = store.snapshot()["calls"][0]
    assert len(item["preview"]) == 500
    assert len(item["purpose"]) == 240
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    store.close()


def test_shorten_and_age_formatting():
    assert shorten("one\ntwo three", 10) == "one two..."
    now = datetime(2026, 7, 22, 12, 0, 10, tzinfo=UTC)
    item = {"created_at": (now - timedelta(seconds=10)).isoformat(), "duration_ms": 0}
    assert format_age(item, now=now) == "10s"


def test_snapshot_keeps_full_redacted_command_and_log_path_metadata(tmp_path):
    store = RealtimeCallStore(redact_text=lambda value: value.replace("secret", "[REDACTED]"))
    store.update({
        **call("detail", "running", datetime.now(UTC).isoformat(), command="echo secret && printf 'two'"),
        "log_path": str(tmp_path / "detail.log"),
    })

    item = store.snapshot()["calls"][0]
    assert item["command"] == "echo [REDACTED] && printf 'two'"
    assert item["log_ref"] == "logs/commands/detail.log"
    assert "log_path" not in item
    assert "command" not in item["preview"] or item["preview"] == item["command"]


def test_read_call_log_handles_missing_and_rotated_files(tmp_path):
    path = tmp_path / "command.log"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert read_call_log(path, offset=4) == {"text": "two\nthree\n", "offset": 14, "size": 14, "rotated": False}
    path.unlink()
    assert read_call_log(path, offset=0) == {"text": "", "offset": 0, "size": 0, "rotated": True}


def test_read_call_log_uses_byte_offsets_and_bounded_bytes(tmp_path):
    path = tmp_path / "command.log"
    path.write_bytes("é\n二\n".encode())
    result = read_call_log(path, offset=3, limit=4)
    assert result["text"] == "二\n"
    assert result["offset"] == 7


def test_store_keeps_generic_activity_context_without_leaking_session_id():
    store = RealtimeCallStore()
    now = datetime.now(UTC).isoformat()
    store.update({
        "execution_id": "activity-1",
        "status": "running",
        "created_at": now,
        "started_at": now,
        "tool": "skills_search",
        "kind": "tool",
        "purpose": "Search skills",
        "conversation_id": "conv_auto_abc123",
        "session_ref": "mcp_123456789abc",
        "request_id": "req-42",
        "cwd": "/projects/irz",
    })

    item = store.snapshot()["calls"][0]
    assert item["kind"] == "tool"
    assert item["conversation_id"] == "conv_auto_abc123"
    assert item["session_ref"] == "mcp_123456789abc"
    assert item["request_id"] == "req-42"
    assert item["working_directory"] == "/projects/irz"


def test_activity_lifecycle_records_running_then_terminal_state():
    store = RealtimeCallStore()

    activity_id = store.start_activity(
        tool="skills_read",
        kind="tool",
        purpose="Read skill",
        conversation_id="conv-auto",
        session_ref="mcp-session",
        request_id="req-1",
    )
    running = store.snapshot()["calls"][0]
    assert running["execution_id"] == activity_id
    assert running["status"] == "running"
    assert running["finished_at"] is None

    store.finish_activity(activity_id, status="success")
    done = store.snapshot()["calls"][0]
    assert done["execution_id"] == activity_id
    assert done["status"] == "success"
    assert done["finished_at"] is not None
    assert done["conversation_id"] == "conv-auto"


def test_auto_conversation_id_is_stable_opaque_and_session_scoped():
    from src import realtime_calls

    first = realtime_calls.auto_conversation_id("raw-session-id-123")
    again = realtime_calls.auto_conversation_id("raw-session-id-123")
    other = realtime_calls.auto_conversation_id("another-session")

    assert first == again
    assert first.startswith("conv_auto_")
    assert first != other
    assert "raw-session-id-123" not in first
    assert realtime_calls.session_ref("raw-session-id-123").startswith("mcp_")
    assert "raw-session-id-123" not in realtime_calls.session_ref("raw-session-id-123")


def test_snapshot_write_failure_does_not_break_activity(monkeypatch, tmp_path, caplog):
    path = tmp_path / "realtime_calls.json"
    store = RealtimeCallStore(snapshot_path=path)

    def fail_write(_self, *_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", fail_write)

    activity_id = store.start_activity(tool="skills_search", purpose="Search skills")
    assert store.flush_snapshot()

    assert activity_id.startswith("activity_")
    assert store.snapshot()["calls"][0]["tool"] == "skills_search"
    assert "snapshot" in caplog.text.lower()
    store.close()


def test_snapshot_updates_are_coalesced_off_the_update_path(monkeypatch, tmp_path):
    store = RealtimeCallStore(snapshot_path=tmp_path / "realtime_calls.json")
    writes = []

    def record_write():
        writes.append(time.monotonic())

    monkeypatch.setattr(store, "_write_snapshot", record_write)
    started = time.monotonic()
    for index in range(10):
        store.update(call(str(index), "success", datetime.now(UTC).isoformat()))
    elapsed = time.monotonic() - started

    assert elapsed < 0.05
    assert store.flush_snapshot()
    assert len(writes) == 1
    store.close()
