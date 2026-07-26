from pathlib import Path
from unittest.mock import Mock

from src import interactive_launcher, tunnel_provider


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


def test_start_ngrok_uses_resolved_target(monkeypatch, tmp_path):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.delenv("GATE_EXISTING_NGROK_PID", raising=False)
    monkeypatch.setattr(interactive_launcher, "NGROK_LOG", tmp_path / "ngrok.log")
    monkeypatch.setattr(interactive_launcher, "resolve_ngrok_target", lambda port: "172.20.10.2:8761")
    monkeypatch.setattr(
        tunnel_provider.shutil,
        "which",
        lambda name: "/usr/bin/ngrok" if name == "ngrok" else None,
    )
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    returned, _ = interactive_launcher.start_tunnel()

    assert returned is process
    assert popen.call_args.args[0][:4] == [
        "ngrok", "http", "172.20.10.2:8761", "--log=stdout",
    ]
    popen.call_args.kwargs["stdout"].close()


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
    monkeypatch.setattr(interactive_launcher, "start_tunnel", lambda: (ngrok, "test"))
    monkeypatch.setattr(interactive_launcher, "wait_for_gateway_health", lambda *args, **kwargs: None)
    monkeypatch.setattr(interactive_launcher, "wait_for_ngrok_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(interactive_launcher, "available_update", lambda: "0.1.6")

    def fake_monitor(*args):
        interactive_launcher.UPDATE_REQUESTED = True
        return 0

    monkeypatch.setattr(interactive_launcher, "monitor", fake_monitor)
    monkeypatch.setattr(interactive_launcher, "terminate_group", lambda process: events.append(("stop", process)))
    monkeypatch.setattr(interactive_launcher, "install_update", lambda: events.append(("update", None)) or 0)
    monkeypatch.setattr(interactive_launcher.os, "execv", lambda *args: None)

    assert interactive_launcher.main() == 0
    assert events == [("stop", ngrok), ("stop", services), ("update", None)]


def test_latest_changelog_returns_current_version_section(monkeypatch, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 0.1.7\n\n### Added\n\n- New menu.\n\n## 0.1.6\n\n- Older.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "CHANGELOG_FILE", changelog)

    assert interactive_launcher.latest_changelog("0.1.7") == "### Added\n\n- New menu."


def test_controls_are_aligned_in_one_key_column():
    lines = interactive_launcher.control_lines("0.1.8")

    assert lines == [
        "[m]    Connection details",
        "[c]    Changelog",
        "[r]    Realtime calls",
        "[u]    Install update 0.1.8",
        "[^C]   Stop Gate",
    ]


def test_update_relaunches_gate_after_success(monkeypatch):
    events = []
    monkeypatch.setattr(interactive_launcher, "install_update", lambda: events.append("update") or 0)
    monkeypatch.setattr(interactive_launcher, "relaunch_gate", lambda: events.append("relaunch") or 0)

    assert interactive_launcher.install_update_and_relaunch() == 0
    assert events == ["update", "relaunch"]


def test_update_does_not_relaunch_after_failure(monkeypatch):
    events = []
    monkeypatch.setattr(interactive_launcher, "install_update", lambda: events.append("update") or 1)
    monkeypatch.setattr(interactive_launcher, "relaunch_gate", lambda: events.append("relaunch") or 0)

    assert interactive_launcher.install_update_and_relaunch() == 1
    assert events == ["update"]


def test_monitor_toggles_panels_with_same_key_and_escape(monkeypatch):
    rendered_panels = []
    keys = iter([b"m", b"m", b"c", b"\x1b", b"u"])

    class Process:
        pid = 123
        def poll(self):
            return None

    class TerminalInput:
        def __enter__(self):
            return 42
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(interactive_launcher, "STOP_REQUESTED", False)
    monkeypatch.setattr(interactive_launcher, "UPDATE_REQUESTED", False)
    monkeypatch.setattr(interactive_launcher, "terminal_input", lambda: TerminalInput())
    monkeypatch.setattr(interactive_launcher.select, "select", lambda *args: ([42], [], []))
    monkeypatch.setattr(interactive_launcher.os, "read", lambda *args: next(keys))
    monkeypatch.setattr(
        interactive_launcher,
        "render_screen",
        lambda services, ngrok, keep_awake, update_version, panel: rendered_panels.append(panel),
    )
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)

    assert interactive_launcher.monitor(Process(), Process(), "active", ["0.1.8"]) == 0
    assert rendered_panels == [None, "connections", None, "changelog", None]
    assert interactive_launcher.UPDATE_REQUESTED is True


def test_monitor_ignores_update_key_while_panel_is_open(monkeypatch):
    rendered_panels = []
    keys = iter([b"m", b"u", b"m", b"u"])

    class Process:
        pid = 123
        def poll(self):
            return None

    class TerminalInput:
        def __enter__(self):
            return 42
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(interactive_launcher, "STOP_REQUESTED", False)
    monkeypatch.setattr(interactive_launcher, "UPDATE_REQUESTED", False)
    monkeypatch.setattr(interactive_launcher, "terminal_input", lambda: TerminalInput())
    monkeypatch.setattr(interactive_launcher.select, "select", lambda *args: ([42], [], []))
    monkeypatch.setattr(interactive_launcher.os, "read", lambda *args: next(keys))
    monkeypatch.setattr(
        interactive_launcher,
        "render_screen",
        lambda services, ngrok, keep_awake, update_version, panel: rendered_panels.append(panel),
    )
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)

    assert interactive_launcher.monitor(Process(), Process(), "active", ["0.1.8"]) == 0
    assert rendered_panels == [None, "connections", None]
    assert interactive_launcher.UPDATE_REQUESTED is True


def test_tailscale_failure_uses_tailscale_log():
    message = interactive_launcher.startup_failure_message("tailscale", 1)
    assert str(interactive_launcher.TAILSCALE_LOG) in message
