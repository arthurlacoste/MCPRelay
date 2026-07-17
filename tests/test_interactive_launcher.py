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


def test_available_update_returns_newer_release(monkeypatch, tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("0.1.5\n")
    monkeypatch.setattr(interactive_launcher, "VERSION_FILE", version_file)
    monkeypatch.setattr(
        interactive_launcher,
        "fetch_latest_release_tag",
        lambda: "v0.1.6",
    )

    assert interactive_launcher.available_update() == "0.1.6"


def test_available_update_ignores_current_or_older_release(monkeypatch, tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("0.1.5\n")
    monkeypatch.setattr(interactive_launcher, "VERSION_FILE", version_file)
    monkeypatch.setattr(interactive_launcher, "fetch_latest_release_tag", lambda: "v0.1.5")
    assert interactive_launcher.available_update() is None

    monkeypatch.setattr(interactive_launcher, "fetch_latest_release_tag", lambda: "v0.1.4")
    assert interactive_launcher.available_update() is None


def test_install_update_runs_global_gate_update(monkeypatch):
    calls = []
    def fake_run(args, check=False):
        calls.append((args, check))
        return interactive_launcher.subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(interactive_launcher.subprocess, "run", fake_run)

    interactive_launcher.install_update()

    assert calls == [([str(interactive_launcher.GATE_COMMAND), "update"], False)]


def test_main_installs_update_after_services_stop(monkeypatch):
    events = []

    class Process:
        pid = 123
        def poll(self): return None

    services = Process()
    ngrok = Process()
    monkeypatch.setattr(interactive_launcher.signal, "signal", lambda *args: None)
    monkeypatch.setattr(interactive_launcher, "start_services", lambda: services)
    monkeypatch.setattr(interactive_launcher, "start_ngrok", lambda: (ngrok, "test"))
    monkeypatch.setattr(interactive_launcher, "wait_for_start", lambda *args: None)
    monkeypatch.setattr(interactive_launcher, "available_update", lambda: "0.1.6")

    def fake_monitor(*args):
        interactive_launcher.UPDATE_REQUESTED = True
        return 0

    monkeypatch.setattr(interactive_launcher, "monitor", fake_monitor)
    monkeypatch.setattr(interactive_launcher, "terminate_group", lambda process: events.append(("stop", process)))
    monkeypatch.setattr(interactive_launcher, "install_update", lambda: events.append(("update", None)) or 0)

    assert interactive_launcher.main() == 0
    assert events == [("stop", ngrok), ("stop", services), ("update", None)]
