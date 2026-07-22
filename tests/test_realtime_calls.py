from datetime import UTC, datetime, timedelta

from src.realtime_calls import RealtimeCallStore, format_age, shorten
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


def test_store_sorts_active_queued_errors_then_success():
    store = RealtimeCallStore()
    base = datetime(2026, 7, 22, tzinfo=UTC)
    store.update(call("done", "success", (base + timedelta(seconds=1)).isoformat()))
    store.update(call("error", "failed", (base + timedelta(seconds=2)).isoformat()))
    store.update(call("queued", "queued", (base + timedelta(seconds=3)).isoformat()))
    store.update(call("running", "running", (base + timedelta(seconds=4)).isoformat()))

    assert [item["execution_id"] for item in store.snapshot()["calls"]] == [
        "running", "queued", "error", "done",
    ]


def test_store_masks_secrets_and_flattens_preview():
    redactor = SecretRedactor(("top-secret-value",))
    store = RealtimeCallStore(redact_text=redactor.redact_text)
    store.update(call(
        "secret", "running", datetime.now(UTC).isoformat(),
        command="curl\n-H 'Authorization: Bearer top-secret-value' --api-key=abc123",
    ))

    preview = store.snapshot()["calls"][0]["preview"]
    assert "top-secret-value" not in preview
    assert "abc123" not in preview
    assert "[REDACTED]" in preview
    assert "\n" not in preview


def test_recent_buffer_is_bounded_but_active_calls_remain():
    store = RealtimeCallStore(max_entries=2)
    now = datetime.now(UTC).isoformat()
    store.update(call("running", "running", now))
    for index in range(3):
        store.update(call(f"done-{index}", "success", now))

    ids = [item["execution_id"] for item in store.snapshot()["calls"]]
    assert ids[0] == "running"
    assert set(ids[1:]) == {"done-1", "done-2"}


def test_shorten_and_age_formatting():
    assert shorten("one\ntwo three", 10) == "one two..."
    now = datetime(2026, 7, 22, 12, 0, 10, tzinfo=UTC)
    item = {"created_at": (now - timedelta(seconds=10)).isoformat(), "duration_ms": 0}
    assert format_age(item, now=now) == "10s"
