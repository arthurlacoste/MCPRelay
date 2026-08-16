from pathlib import Path
from unittest.mock import Mock

from src import interactive_launcher, tunnel_provider


def test_connection_details_include_public_realtime_url(tmp_path, monkeypatch):
    config = tmp_path / ".env"
    config.write_text(
        "MCP_BASE_URL=https://gate.example\nOAUTH_ACCESS_SECRET=secret\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", config)

    assert (
        "Public realtime: https://gate.example/rt"
        in interactive_launcher.connection_detail_lines()
    )


def test_log_tail_returns_only_last_lines(tmp_path):
    log = tmp_path / "launcher.log"
    log.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    assert interactive_launcher.log_tail(log, max_lines=2) == "three\nfour"


def test_realtime_detail_renders_safe_full_command_and_log(tmp_path, monkeypatch, capsys):
    log = tmp_path / "commands" / "safe.log"
    log.parent.mkdir()
    log.write_text("output\n", encoding="utf-8")
    monkeypatch.setattr(interactive_launcher, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(interactive_launcher, "REALTIME_CALLS_FILE", tmp_path / "calls.json")
    (tmp_path / "calls.json").write_text('{"calls": [{"status":"running", "command":"echo a\\nb\\t\\u001b[2J", "log_ref":"logs/commands/safe.log"}]}')
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)
    monkeypatch.setattr(interactive_launcher.shutil, "get_terminal_size", lambda _: (120, 30))
    interactive_launcher.render_realtime_panel(details=True)
    output = capsys.readouterr().out
    assert "echo a\nb\t" in output
    assert "echo a\nb\t\x1b" not in output
    assert "output" in output


def test_realtime_detail_reserves_height_for_multiline_command(tmp_path, monkeypatch, capsys):
    log = tmp_path / "commands" / "safe.log"
    log.parent.mkdir()
    log.write_text("\n".join(f"log-{index}" for index in range(20)) + "\n", encoding="utf-8")
    monkeypatch.setattr(interactive_launcher, "LOG_ROOT", tmp_path)
    monkeypatch.setattr(interactive_launcher, "REALTIME_CALLS_FILE", tmp_path / "calls.json")
    command = "\n".join(f"cmd-{index}" for index in range(5))
    (tmp_path / "calls.json").write_text(
        __import__("json").dumps({"calls": [{
            "status": "running",
            "command": command,
            "log_ref": "logs/commands/safe.log",
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)
    monkeypatch.setattr(interactive_launcher.shutil, "get_terminal_size", lambda _: (120, 20))

    interactive_launcher.render_realtime_panel(details=True)

    output = capsys.readouterr().out
    assert "log-19" in output
    assert "log-18" not in output


def test_realtime_detail_surfaces_command_truncation(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(interactive_launcher, "REALTIME_CALLS_FILE", tmp_path / "calls.json")
    (tmp_path / "calls.json").write_text(
        '{"calls": [{"status":"success", "command":"echo ok", "command_truncated":true}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)
    monkeypatch.setattr(interactive_launcher.shutil, "get_terminal_size", lambda _: (120, 30))

    interactive_launcher.render_realtime_panel(details=True)

    assert "command truncated" in capsys.readouterr().out.lower()


def test_resolve_realtime_log_ref_rejects_absolute_and_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(interactive_launcher, "LOG_ROOT", tmp_path)
    for value in ("/etc/passwd", "logs/commands/../../secret.log", "logs/commands/sub/ok.log"):
        assert interactive_launcher.resolve_realtime_log(value) is None


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
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", tmp_path / ".env")
    monkeypatch.delenv("GATE_EXISTING_NGROK_PID", raising=False)
    monkeypatch.delenv("TUNNEL_PROVIDER", raising=False)
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

class _AlwaysAliveProcess:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None


def test_start_tailscale_reuses_existing_active_funnel(monkeypatch, tmp_path):
    monkeypatch.setenv("TUNNEL_PROVIDER", "tailscale")
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", tmp_path / ".env")
    monkeypatch.delenv("GATE_EXISTING_TAILSCALE_PID", raising=False)
    monkeypatch.setattr(
        interactive_launcher, "tailscale_public_url", lambda port=None: "https://mj-1.taildc7e9e.ts.net"
    )
    popen = Mock()
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    returned, label = interactive_launcher.start_tunnel()

    assert isinstance(returned, interactive_launcher.ExistingFunnel)
    assert label == "existing funnel reused"
    popen.assert_not_called()


def test_start_tailscale_reuses_onboarding_process(monkeypatch, tmp_path):
    monkeypatch.setenv("TUNNEL_PROVIDER", "tailscale")
    monkeypatch.setenv("GATE_EXISTING_TAILSCALE_PID", "4242")
    monkeypatch.setattr(interactive_launcher, "ExistingProcess", _AlwaysAliveProcess)
    monkeypatch.setattr(interactive_launcher, "build_tunnel_spec", Mock())

    returned, label = interactive_launcher.start_tunnel()

    assert returned.pid == 4242
    assert label == "onboarding tunnel reused"
    interactive_launcher.build_tunnel_spec.assert_not_called()


def test_start_tailscale_starts_new_funnel_when_none_active(monkeypatch, tmp_path):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setenv("TUNNEL_PROVIDER", "tailscale")
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", tmp_path / ".env")
    monkeypatch.delenv("GATE_EXISTING_TAILSCALE_PID", raising=False)
    monkeypatch.setattr(
        interactive_launcher, "tailscale_public_url", Mock(side_effect=interactive_launcher.TunnelConfigurationError)
    )
    monkeypatch.setattr(
        interactive_launcher.shutil,
        "which",
        lambda name: "/usr/bin/tailscale" if name == "tailscale" else None,
    )
    monkeypatch.setattr(tunnel_provider, "validate_tailscale_session", lambda: None)
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    returned, label = interactive_launcher.start_tunnel()

    assert returned is process
    assert label == "sleep inhibition inactive"
    assert popen.call_args.args[0] == ["tailscale", "funnel", "--bg=false", "8761"]
    popen.call_args.kwargs["stdout"].close()


def test_existing_funnel_poll_detects_dead_funnel(monkeypatch):
    times = iter([0.0, 100.0])
    monkeypatch.setattr(interactive_launcher.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        interactive_launcher,
        "tailscale_public_url",
        Mock(side_effect=interactive_launcher.TunnelConfigurationError),
    )

    funnel = interactive_launcher.ExistingFunnel()
    assert funnel.poll() is None  # throttled: within the check interval
    assert funnel.poll() == 1     # re-check: the Funnel is gone


def test_existing_funnel_poll_keeps_none_while_active(monkeypatch):
    times = iter([0.0, 100.0])
    monkeypatch.setattr(interactive_launcher.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        interactive_launcher,
        "tailscale_public_url",
        lambda port=None: "https://mj-1.taildc7e9e.ts.net",
    )

    funnel = interactive_launcher.ExistingFunnel()
    assert funnel.poll() is None
    assert funnel.poll() is None


def test_terminate_group_leaves_reused_funnel_alone(monkeypatch):
    funnel = interactive_launcher.ExistingFunnel()
    signals = []
    monkeypatch.setattr(interactive_launcher.os, "killpg", lambda *args: signals.append(args))
    monkeypatch.setattr(interactive_launcher.os, "kill", lambda *args: signals.append(args))

    interactive_launcher.terminate_group(funnel)

    assert signals == []


def test_wait_for_tailscale_ready_checks_proxy_port(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        interactive_launcher,
        "tailscale_public_url",
        lambda port=None: seen.setdefault("port", port) or "https://mj-1.taildc7e9e.ts.net",
    )
    monkeypatch.setattr(interactive_launcher, "STOP_REQUESTED", False)

    class Alive:
        def poll(self):
            return None

    interactive_launcher.wait_for_tailscale_ready(Alive())
    assert seen["port"] == interactive_launcher.NGROK_PORT


def test_start_cloudflared_uses_loopback_url(monkeypatch, tmp_path):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setenv("TUNNEL_PROVIDER", "cloudflare")
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", tmp_path / ".env")
    monkeypatch.delenv("CLOUDFLARED_TUNNEL_NAME", raising=False)
    monkeypatch.delenv("GATE_EXISTING_CLOUDFLARED_PID", raising=False)
    monkeypatch.setattr(interactive_launcher, "CLOUDFLARED_LOG", tmp_path / "cloudflared.log")
    monkeypatch.setattr(
        tunnel_provider.shutil,
        "which",
        lambda name: "/usr/bin/cloudflared" if name == "cloudflared" else None,
    )
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    returned, _ = interactive_launcher.start_tunnel()

    assert returned is process
    assert popen.call_args.args[0] == [
        "cloudflared", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8761",
    ]
    popen.call_args.kwargs["stdout"].close()


def test_start_cloudflared_named_tunnel_uses_tunnel_name(monkeypatch, tmp_path):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setenv("TUNNEL_PROVIDER", "cloudflare")
    monkeypatch.setenv("CLOUDFLARED_TUNNEL_NAME", "gate")
    monkeypatch.delenv("GATE_EXISTING_CLOUDFLARED_PID", raising=False)
    monkeypatch.setattr(interactive_launcher, "CLOUDFLARED_LOG", tmp_path / "cloudflared.log")
    monkeypatch.setattr(
        tunnel_provider.shutil,
        "which",
        lambda name: "/usr/bin/cloudflared" if name == "cloudflared" else None,
    )
    monkeypatch.setattr(interactive_launcher.subprocess, "Popen", popen)

    returned, _ = interactive_launcher.start_tunnel()

    assert returned is process
    assert popen.call_args.args[0] == [
        "cloudflared", "tunnel", "--no-autoupdate", "run", "--url", "http://127.0.0.1:8761", "gate",
    ]
    popen.call_args.kwargs["stdout"].close()


def test_start_cloudflared_reuses_onboarding_tunnel(monkeypatch, tmp_path):
    class FakeExistingProcess:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

    monkeypatch.setenv("TUNNEL_PROVIDER", "cloudflare")
    monkeypatch.setenv("GATE_EXISTING_CLOUDFLARED_PID", "4242")
    monkeypatch.setattr(interactive_launcher, "ExistingProcess", FakeExistingProcess)
    monkeypatch.setattr(interactive_launcher, "build_tunnel_spec", Mock())

    returned, label = interactive_launcher.start_tunnel()

    assert returned.pid == 4242
    assert label == "onboarding tunnel reused"
    interactive_launcher.build_tunnel_spec.assert_not_called()


def test_cloudflared_failure_uses_cloudflared_log():
    message = interactive_launcher.startup_failure_message("cloudflare", 1)
    assert str(interactive_launcher.CLOUDFLARED_LOG) in message


def test_wait_for_cloudflared_ready_returns_when_url_appears(monkeypatch, tmp_path):
    log = tmp_path / "cloudflared.log"
    monkeypatch.setattr(interactive_launcher, "CLOUDFLARED_LOG", log)

    class Process:
        pid = 123
        def poll(self):
            return None

    def fake_url(_):
        log.write_text("INF | https://magic-tunnels-9.trycloudflare.com |\n", encoding="utf-8")
        return "https://magic-tunnels-9.trycloudflare.com"

    monkeypatch.setattr(interactive_launcher, "cloudflared_public_url", fake_url)
    interactive_launcher.wait_for_cloudflared_ready(Process())


def test_wait_for_cloudflared_ready_returns_when_registered(monkeypatch, tmp_path):
    log = tmp_path / "cloudflared.log"
    monkeypatch.setattr(interactive_launcher, "CLOUDFLARED_LOG", log)
    monkeypatch.setattr(interactive_launcher, "cloudflared_public_url", lambda _: "")

    class Process:
        pid = 123
        def poll(self):
            return None

    def fake_registered(_):
        log.write_text("INF Registered tunnel connection connIndex=0", encoding="utf-8")
        return True

    monkeypatch.setattr(interactive_launcher, "cloudflared_registered", fake_registered)
    interactive_launcher.wait_for_cloudflared_ready(Process())


def test_wait_for_cloudflared_ready_reports_failure(monkeypatch, tmp_path):
    log = tmp_path / "cloudflared.log"
    monkeypatch.setattr(interactive_launcher, "CLOUDFLARED_LOG", log)
    monkeypatch.setattr(interactive_launcher, "STOP_REQUESTED", False)
    monkeypatch.setattr(interactive_launcher, "cloudflared_public_url", lambda _: "")
    monkeypatch.setattr(interactive_launcher.time, "monotonic", lambda: 0)

    class Process:
        pid = 123
        def poll(self):
            return None

    try:
        interactive_launcher.wait_for_cloudflared_ready(Process(), timeout=0.0)
    except interactive_launcher.StartupError as exc:
        assert "Cloudflare Tunnel did not become ready" in str(exc)
    else:
        raise AssertionError("expected StartupError")


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


def test_main_installs_update_after_services_stop(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(interactive_launcher, "CONFIG_FILE", tmp_path / ".env")
    monkeypatch.delenv("TUNNEL_PROVIDER", raising=False)

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


def test_latest_changelog_reads_release_please_heading(monkeypatch, tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [0.1.26](https://github.com/spelcc/gate/compare/v0.1.25...v0.1.26) (2026-08-16)\n\n"
        "### Added\n\n"
        "* add discover-first MCP tool exposure\n\n"
        "## [0.1.25](https://example.test/previous) (2026-08-15)\n\n"
        "* Previous.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "CHANGELOG_FILE", changelog)

    assert interactive_launcher.latest_changelog("0.1.26") == (
        "### Added\n\n* add discover-first MCP tool exposure"
    )


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


def test_terminal_input_restores_raw_and_output_modes(monkeypatch):
    events = []

    class FakeInput:
        def isatty(self):
            return True

        def fileno(self):
            return 42

    monkeypatch.setattr(interactive_launcher.sys, "stdin", FakeInput())
    monkeypatch.setattr(interactive_launcher, "restore_terminal_output", lambda: events.append("output-reset"))
    monkeypatch.setattr(interactive_launcher.termios, "tcgetattr", lambda fd: events.append(("get", fd)) or [1, 2, 3])
    monkeypatch.setattr(interactive_launcher.tty, "setcbreak", lambda fd: events.append(("cbreak", fd)))
    monkeypatch.setattr(
        interactive_launcher.termios,
        "tcsetattr",
        lambda fd, when, attrs: events.append(("restore", fd, when, attrs)),
    )

    with interactive_launcher.terminal_input() as fd:
        assert fd == 42
        events.append("body")

    assert events == [
        "output-reset",
        ("get", 42),
        ("cbreak", 42),
        "body",
        ("restore", 42, interactive_launcher.termios.TCSADRAIN, [1, 2, 3]),
        "output-reset",
    ]


def test_main_handles_sighup_when_available(monkeypatch):
    if not hasattr(interactive_launcher.signal, "SIGHUP"):
        return

    installed = []
    monkeypatch.setattr(interactive_launcher.signal, "signal", lambda sig, handler: installed.append((sig, handler)))
    monkeypatch.setattr(
        interactive_launcher,
        "start_services",
        lambda: (_ for _ in ()).throw(interactive_launcher.ShutdownRequested()),
    )
    monkeypatch.setattr(interactive_launcher, "restore_terminal_output", lambda: None)

    assert interactive_launcher.main() == 0
    assert (interactive_launcher.signal.SIGHUP, interactive_launcher.request_shutdown) in installed


def test_realtime_detail_shows_activity_correlation_fields(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(interactive_launcher, "REALTIME_CALLS_FILE", tmp_path / "calls.json")
    (tmp_path / "calls.json").write_text(
        __import__("json").dumps({"calls": [{
            "status": "success",
            "tool": "oauth.token",
            "kind": "oauth",
            "purpose": "POST /oauth/token",
            "conversation_id": "conv_auto_deadbeef",
            "session_ref": "mcp_deadbeef",
            "request_id": "req-123",
            "http_status": 200,
        }]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(interactive_launcher, "clear_terminal", lambda: None)
    monkeypatch.setattr(interactive_launcher.shutil, "get_terminal_size", lambda _: (120, 30))

    interactive_launcher.render_realtime_panel(details=True)

    output = capsys.readouterr().out
    assert "Kind:     oauth" in output
    assert "Conversation: conv_auto_deadbeef" in output
    assert "Session:  mcp_deadbeef" in output
    assert "Request:  req-123" in output
    assert "HTTP:     200" in output
