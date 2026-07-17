from pathlib import Path
from unittest.mock import Mock

from src import interactive_launcher


def test_log_tail_returns_only_last_lines(tmp_path):
    log = tmp_path / "launcher.log"
    log.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    assert interactive_launcher.log_tail(log, max_lines=2) == "three\nfour"


def test_gateway_startup_failure_includes_log_output(monkeypatch, tmp_path):
    log = tmp_path / "launcher.log"
    log.write_text(
        "gateway port 8761 is already in use; "
        "stop the existing gateway before starting a new one\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "SERVICE_LOG", log)

    message = interactive_launcher.startup_failure_message("Gateway", 1)

    assert "Gateway failed to start (exit 1)." in message
    assert "gateway port 8761 is already in use" in message
    assert f"Full log: {log}" in message


def test_ngrok_startup_failure_points_to_ngrok_log():
    message = interactive_launcher.startup_failure_message("ngrok", 1)

    assert message == (
        f"ngrok failed to start (exit 1). Check {interactive_launcher.NGROK_LOG}."
    )


def test_start_services_captures_output(monkeypatch, tmp_path):
    log = tmp_path / "launcher.log"
    popen = Mock(return_value=Mock())
    monkeypatch.setattr(interactive_launcher, "SERVICE_LOG", log)
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    interactive_launcher.start_services()

    kwargs = popen.call_args.kwargs
    assert kwargs["stderr"] == interactive_launcher.subprocess.STDOUT
    assert kwargs["stdout"].name == str(log)
    kwargs["stdout"].close()
