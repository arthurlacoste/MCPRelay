from pathlib import Path

from agent_manager.models import AgentRecord
from agent_manager.notifications import (
    notification_payload,
    notify_agent_finished,
    result_summary,
)


def make_record() -> AgentRecord:
    return AgentRecord(
        agent_id="agt_test",
        status="completed",
        prompt="hello",
        purpose="Apple Notes: Meteo",
        metadata={"note_title": "Taches a faire"},
    )


def test_result_summary_prefers_stdout_tail():
    result = {"stdout": "line 1\nline 2\nline 3\nline 4\nline 5\n"}

    summary = result_summary(result, 200)

    assert "line 1" not in summary
    assert "line 2" in summary
    assert "line 5" in summary


def test_notification_payload_contains_status_result_and_url():
    payload = notification_payload(
        make_record(),
        "completed",
        {"stdout": "Meteo a Grenoble : 19.5 C"},
        {"include_url": True, "include_stdout_chars": 100},
    )

    assert payload["title"] == "Agent termine: Apple Notes: Meteo"
    assert payload["subtitle"] == "Taches a faire"
    assert "Status: completed" in payload["message"]
    assert "Meteo a Grenoble" in payload["message"]
    assert "http://localhost:8761/agents/agt_test" in payload["message"]


def test_notify_agent_finished_can_be_disabled(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "scheduler.yaml").write_text(
        "notifications:\n  enabled: false\n",
        encoding="utf-8",
    )

    result = notify_agent_finished(
        make_record(),
        "completed",
        {"stdout": "done"},
        base_dir=tmp_path,
    )

    assert result == {"ok": True, "sent": False, "reason": "disabled"}


def test_notify_agent_finished_sends_macos_notification(monkeypatch, tmp_path: Path):
    calls = []
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "scheduler.yaml").write_text(
        "notifications:\n  enabled: true\n  macos: true\n",
        encoding="utf-8",
    )

    def fake_send(payload):
        calls.append(payload)

    monkeypatch.setattr("agent_manager.notifications.send_macos_notification", fake_send)

    result = notify_agent_finished(
        make_record(),
        "failed",
        {"error": "boom"},
        base_dir=tmp_path,
    )

    assert result["ok"] is True
    assert result["sent"] is True
    assert result["channel"] == "macos"
    assert calls
    assert "boom" in calls[0]["message"]
