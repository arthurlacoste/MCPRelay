import json
from io import StringIO

from gate_cli.log_viewer import follow_snapshot, render_snapshot


def write_snapshot(path, calls):
    path.write_text(json.dumps({"updated_at": None, "calls": calls}), encoding="utf-8")


def test_render_snapshot_limits_rows_to_terminal_height(tmp_path):
    snapshot = tmp_path / "realtime_calls.json"
    calls = [
        {
            "execution_id": f"exec-{index}",
            "status": "done",
            "created_at": "2026-07-23T12:00:00+00:00",
            "started_at": "2026-07-23T12:00:00+00:00",
            "finished_at": "2026-07-23T12:00:01+00:00",
            "duration_ms": 1000,
            "tool": "run_command",
            "purpose": f"Task {index}",
            "preview": "",
        }
        for index in range(5)
    ]
    write_snapshot(snapshot, calls)

    output = render_snapshot(snapshot, width=100, height=11)

    assert "Task 0" in output
    assert "Task 1" in output
    assert "Task 2" not in output


def test_follow_snapshot_non_interactive_prints_once(tmp_path):
    snapshot = tmp_path / "realtime_calls.json"
    write_snapshot(snapshot, [{
        "execution_id": "exec-1",
        "status": "failed",
        "created_at": "2026-07-23T12:00:00+00:00",
        "started_at": "2026-07-23T12:00:00+00:00",
        "finished_at": "2026-07-23T12:00:02+00:00",
        "duration_ms": 2000,
        "tool": "filesystem_execute_tool",
        "purpose": "Read gateway logs",
        "preview": "cat logs/services/gateway.log",
    }])
    stream = StringIO()

    assert follow_snapshot(snapshot, stream=stream, interactive=False) == 0
    assert stream.getvalue().count("Realtime calls") == 1
    assert "FAILED" in stream.getvalue()


def test_follow_snapshot_rejects_empty_data(tmp_path):
    snapshot = tmp_path / "realtime_calls.json"
    write_snapshot(snapshot, [])
    stream = StringIO()

    assert follow_snapshot(snapshot, stream=stream, interactive=False) == 1
    assert "No realtime log data" in stream.getvalue()


def test_follow_snapshot_handles_interrupt_during_render(tmp_path, monkeypatch):
    snapshot = tmp_path / "realtime_calls.json"
    write_snapshot(snapshot, [{"status": "running"}])
    stream = StringIO()
    monkeypatch.setattr(
        "gate_cli.log_viewer.render_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    assert follow_snapshot(snapshot, stream=stream, interactive=True) == 130
    assert "Detached from Gate logs." in stream.getvalue()


def test_follow_snapshot_patches_interactive_rows_without_reclearing(tmp_path, monkeypatch):
    snapshot = tmp_path / "realtime_calls.json"
    write_snapshot(snapshot, [{"status": "running"}])
    outputs = iter([
        "Realtime calls\nRUNNING 1s",
        "Realtime calls\nRUNNING 2s",
    ])

    def fake_render(*_args, **_kwargs):
        try:
            return next(outputs)
        except StopIteration:
            raise KeyboardInterrupt

    monkeypatch.setattr("gate_cli.log_viewer.render_snapshot", fake_render)
    monkeypatch.setattr("gate_cli.log_viewer.time.sleep", lambda _seconds: None)
    stream = StringIO()

    assert follow_snapshot(snapshot, stream=stream, interactive=True) == 130
    output = stream.getvalue()
    assert output.count("\x1b[2J\x1b[H") == 1
    assert "\x1b[2;1H\x1b[2KRUNNING 2s" in output
