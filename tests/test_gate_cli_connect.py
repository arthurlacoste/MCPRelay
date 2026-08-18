import json
import os
import subprocess
import sys
from pathlib import Path

from gate_cli import connect


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


# ── CLI presence and install ────────────────────────────────────────────────


def test_tailscale_bin_finds_and_misses_cli():
    assert connect.tailscale_bin(which=lambda _: "/usr/bin/tailscale") == "/usr/bin/tailscale"
    assert connect.tailscale_bin(which=lambda _: None) is None


def test_install_script_per_platform():
    assert "brew install tailscale" in connect.tailscale_install_script("darwin")
    assert "winget install" in connect.tailscale_install_script("windows")
    assert "tailscale.com/install.sh" in connect.tailscale_install_script("linux")


def test_daemon_start_commands_per_platform():
    brew = lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None
    assert connect.tailscale_daemon_start_commands("darwin", which=brew) == [
        ["sudo", "--preserve-env=HOME", "brew", "services", "start", "tailscale"],
        ["open", "-a", "Tailscale"],
    ]
    assert connect.tailscale_daemon_start_commands("linux", which=lambda _: "/usr/bin/systemctl") == [
        ["sudo", "systemctl", "start", "tailscaled"],
    ]
    assert connect.tailscale_daemon_start_commands("windows") == [["sc", "start", "Tailscale"]]


def test_windows_daemon_failure_explains_elevation_requirement():
    message = connect.tailscale_daemon_failure_message(
        "windows", {"error": "Access is denied."}
    )
    assert "Administrator" in message
    assert "sc start Tailscale" in message


# ── Status / login ──────────────────────────────────────────────────────────


def test_tailscale_status_parses_running_session():
    run = lambda *a, **k: completed(stdout=json.dumps({"BackendState": "Running"}))
    assert connect.tailscale_status(run=run)["BackendState"] == "Running"


def test_tailscale_status_reports_failed_daemon():
    run = lambda *a, **k: completed(code=1, stderr="no state")
    assert "not authenticated" in connect.tailscale_status(run=run)["error"]


def test_tailscale_status_detects_missing_daemon_socket():
    run = lambda *a, **k: completed(
        code=1,
        stderr="dial unix /var/run/tailscaled.socket: connect: no such file or directory",
    )
    status = connect.tailscale_status(run=run)
    assert status["daemon_unavailable"]
    assert connect.tailscale_daemon_unavailable(status)


def test_tailscale_status_does_not_treat_generic_missing_file_as_daemon_failure():
    run = lambda *a, **k: completed(code=1, stderr="state file: no such file or directory")
    status = connect.tailscale_status(run=run)
    assert not status["daemon_unavailable"]
    assert not connect.tailscale_daemon_unavailable(status)


def test_tailscale_status_timeout_is_not_daemon_unavailable():
    def hung_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", connect.TAILSCALE_TIMEOUT_SECONDS))

    status = connect.tailscale_status(run=hung_run)
    assert status["timed_out"]
    assert not status.get("daemon_unavailable")
    assert not connect.tailscale_daemon_unavailable(status)


def test_stopped_backend_is_not_daemon_unavailable():
    assert not connect.tailscale_daemon_unavailable({"BackendState": "Stopped"})


def test_tailscale_status_handles_bad_json():
    run = lambda *a, **k: completed(stdout="not json")
    assert "Could not read" in connect.tailscale_status(run=run)["error"]


def test_logged_in_requires_running_backend():
    assert connect.tailscale_logged_in({"BackendState": "Running"}) == (True, "")
    ok, detail = connect.tailscale_logged_in({"BackendState": "Stopped"})
    assert not ok and "not running" in detail


# ── Operator permission ─────────────────────────────────────────────────────


def test_operator_allows_serve_when_operator_matches_user():
    run = lambda *a, **k: completed(stdout=json.dumps({"OperatorUser": connect.current_user()}))
    allowed, _ = connect.operator_allows_serve(run=run)
    assert allowed


def test_operator_denied_when_operator_unset():
    run = lambda *a, **k: completed(stdout=json.dumps({"OperatorUser": None}))
    allowed, diagnostic = connect.operator_allows_serve(run=run)
    assert not allowed
    assert "not set" in diagnostic.lower()


def test_operator_denied_when_operator_is_another_user():
    other = "root" if connect.current_user() != "root" else "someone-else"
    run = lambda *a, **k: completed(stdout=json.dumps({"OperatorUser": other}))
    allowed, diagnostic = connect.operator_allows_serve(run=run)
    assert not allowed
    assert other in diagnostic


def test_operator_falls_back_to_funnel_probe_when_prefs_denied():
    def fake_run(cmd, **kwargs):
        if cmd[1] == "debug":
            return completed(code=1, stderr="debug not allowed")
        return completed(code=1, stderr="Funnel is not enabled for this node")

    allowed, _ = connect.operator_allows_serve(run=fake_run)
    assert allowed  # funnel-not-enabled is a feature toggle, not a permission problem


def test_fix_operator_uses_current_user():
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return completed()

    connect.fix_operator_permission(run=fake_run)
    assert seen["cmd"] == ["sudo", "tailscale", "set", "--operator=" + connect.current_user()]


# ── Funnel summary ──────────────────────────────────────────────────────────


def test_funnel_summary_configured():
    run = lambda *a, **k: completed(stdout='{"Funnel": {"On": true}}')
    assert "configured and ready" in connect.funnel_summary(run=run)


def test_funnel_summary_guides_admin_console_when_disabled():
    run = lambda *a, **k: completed(code=1, stderr="Funnel is not enabled for this node")
    assert "Enable Funnel" in connect.funnel_summary(run=run)


# ── End-to-end flow ─────────────────────────────────────────────────────────


def test_ensure_tailscale_stopped_backend_keeps_login_flow():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "status":
            return completed(stdout=json.dumps({"BackendState": "Stopped"}))
        return completed()

    ready, message = connect.ensure_tailscale(
        which=lambda _: "/usr/bin/tailscale",
        platform="linux",
        input_fn=lambda _: "n",
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert not ready
    assert "Log in with" in message
    assert ["sudo", "systemctl", "start", "tailscaled"] not in calls


def test_start_tailscale_daemon_uses_macos_brew_service():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tailscale":
            return completed(stdout=json.dumps({"BackendState": "Running"}))
        return completed()

    assert connect.start_tailscale_daemon(
        system="darwin",
        which=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert ["sudo", "--preserve-env=HOME", "brew", "services", "start", "tailscale"] in calls


def test_start_tailscale_daemon_polls_after_start():
    calls = []
    now = [0.0]

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tailscale":
            if sum(call[1] == "status" for call in calls) < 2:
                return completed(code=1, stderr="Failed to connect to local Tailscale daemon")
            return completed(stdout=json.dumps({"BackendState": "Running"}))
        return completed()

    def monotonic():
        value = now[0]
        now[0] += 1
        return value

    assert connect.start_tailscale_daemon(
        system="windows",
        run=fake_run,
        print_fn=lambda _: None,
        sleep_fn=lambda _: None,
        monotonic_fn=monotonic,
    )
    assert ["sc", "start", "Tailscale"] in calls


def test_start_tailscale_daemon_skips_missing_start_binary():
    def fake_run(cmd, **kwargs):
        raise OSError(f"{cmd[0]} not found")

    assert not connect.start_tailscale_daemon(
        system="linux",
        which=lambda _: "/usr/bin/systemctl",
        run=fake_run,
        print_fn=lambda _: None,
    )


def test_start_tailscale_daemon_skips_hung_start_command():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sudo" or cmd[0] == "sc":
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        if cmd[0] == "tailscale":
            return completed(stdout=json.dumps({"BackendState": "Running"}))
        return completed()

    assert connect.start_tailscale_daemon(
        system="darwin",
        which=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert ["open", "-a", "Tailscale"] in calls


def test_start_tailscale_daemon_macos_falls_back_to_app_when_brew_fails():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sudo":
            return completed(code=1, stderr="Error: unknown command")
        if cmd[0] == "tailscale":
            return completed(stdout=json.dumps({"BackendState": "Running"}))
        return completed()

    assert connect.start_tailscale_daemon(
        system="darwin",
        which=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert ["sudo", "--preserve-env=HOME", "brew", "services", "start", "tailscale"] in calls
    assert ["open", "-a", "Tailscale"] in calls


def test_start_tailscale_daemon_windows_sc_failure_never_polls():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sc":
            return completed(code=1, stderr="The service is not responding")
        return completed(stdout=json.dumps({"BackendState": "Running"}))

    assert not connect.start_tailscale_daemon(
        system="windows",
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert ["sc", "start", "Tailscale"] in calls
    assert not any(cmd[0] == "tailscale" for cmd in calls)


def test_start_tailscale_daemon_polls_through_status_timeouts():
    calls = []
    now = [0.0]

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tailscale":
            if sum(call[1] == "status" for call in calls) < 3:
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
            return completed(stdout=json.dumps({"BackendState": "Running"}))
        return completed()

    def monotonic():
        value = now[0]
        now[0] += 1
        return value

    assert connect.start_tailscale_daemon(
        system="windows",
        run=fake_run,
        print_fn=lambda _: None,
        sleep_fn=lambda _: None,
        monotonic_fn=monotonic,
    )
    # Two hung status calls are retried (timeouts are not daemon failures).
    assert sum(call[1] == "status" for call in calls if call[0] == "tailscale") == 3


def test_start_tailscale_daemon_gives_up_after_deadline_when_status_hangs():
    calls = []
    now = [0.0]

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tailscale":
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return completed()

    def monotonic():
        value = now[0]
        now[0] += 5
        return value

    assert not connect.start_tailscale_daemon(
        system="windows",
        run=fake_run,
        print_fn=lambda _: None,
        sleep_fn=lambda _: None,
        monotonic_fn=monotonic,
    )
    # The 10s deadline governs; a hung 1s status call does not exhaust it.
    assert sum(call[1] == "status" for call in calls if call[0] == "tailscale") == 2


def test_ensure_tailscale_timeout_reports_without_starting_daemon():
    calls = []

    def hung_run(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", connect.TAILSCALE_TIMEOUT_SECONDS))

    ready, message = connect.ensure_tailscale(
        which=lambda _: "/usr/bin/tailscale",
        platform="linux",
        run=hung_run,
        print_fn=lambda _: None,
    )
    assert not ready
    assert "timed out" in message
    assert not any("start" in cmd for cmd in calls)


def test_ensure_tailscale_windows_sc_failure_explains_elevation():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sc":
            return completed(code=1, stderr="Access is denied.")
        if cmd[0] == "tailscale":
            return completed(code=1, stderr="Failed to connect to local Tailscale daemon")
        return completed()

    ready, message = connect.ensure_tailscale(
        which=lambda _: "/usr/bin/tailscale",
        platform="windows",
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert not ready
    assert "Administrator" in message
    assert "sc start Tailscale" in message


def test_start_tailscale_daemon_reports_failure_after_retries():
    calls = []
    now = [0.0]

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "tailscale":
            return completed(code=1, stderr="Failed to connect to local Tailscale daemon")
        return completed()

    def monotonic():
        value = now[0]
        now[0] += 5
        return value

    assert not connect.start_tailscale_daemon(
        system="linux",
        which=lambda _: "/usr/bin/systemctl",
        run=fake_run,
        print_fn=lambda _: None,
        sleep_fn=lambda _: None,
        monotonic_fn=monotonic,
    )
    assert ["sudo", "systemctl", "start", "tailscaled"] in calls
    assert sum(call[1] == "status" for call in calls if call[0] == "tailscale") == 2


def test_ensure_tailscale_starts_missing_daemon():
    calls = []
    state = {"daemon_running": False}

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "sudo":
            state["daemon_running"] = True
            return completed()
        if cmd[1] == "status":
            if state["daemon_running"]:
                return completed(stdout=json.dumps({"BackendState": "Running"}))
            return completed(code=1, stderr="dial unix /var/run/tailscaled.socket: no such file or directory")
        if cmd[1] == "debug":
            return completed(stdout=json.dumps({"OperatorUser": connect.current_user()}))
        if cmd[1] == "funnel":
            return completed(stdout='{"Funnel": {"On": true}}')
        return completed()

    ready, _ = connect.ensure_tailscale(
        which=lambda _: "/usr/bin/tailscale",
        platform="linux",
        run=fake_run,
        print_fn=lambda _: None,
    )
    assert ready
    assert ["sudo", "systemctl", "start", "tailscaled"] in calls


def test_ensure_tailscale_full_flow_install_login_operator(tmp_path):
    calls = []
    state = {"logged_in": False, "operator_fixed": False}

    def fake_which(_):
        return str(tmp_path / "tailscale") if calls else None

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if isinstance(cmd, str):
            return completed()  # install shell one-liner
        if cmd[0] == "sudo" and cmd[1] == "tailscale" and cmd[2] == "up":
            state["logged_in"] = True
            return completed()
        if cmd[0] == "sudo" and cmd[1] == "tailscale" and cmd[2] == "set":
            state["operator_fixed"] = True
            return completed()
        if cmd[1] == "debug":
            if state["operator_fixed"]:
                return completed(stdout=json.dumps({"OperatorUser": connect.current_user()}))
            return completed(stdout=json.dumps({"OperatorUser": None}))
        if cmd[1] == "funnel":
            if state["operator_fixed"]:
                return completed(stdout=json.dumps({"Funnel": {"On": True}}))
            return completed(code=1, stderr="Access denied: serve config denied")
        if cmd[1] == "status":
            if state["logged_in"]:
                return completed(stdout=json.dumps({"BackendState": "Running"}))
            return completed(code=1, stderr="not logged in")
        return completed()

    answers = iter(["y", "y", "y"])

    ready, message = connect.ensure_tailscale(
        which=fake_which, input_fn=lambda _: next(answers), run=fake_run, print_fn=lambda _: None
    )
    assert ready
    assert ["sudo", "tailscale", "up"] in calls
    assert ["sudo", "tailscale", "set", f"--operator={connect.current_user()}"] in calls
    assert "configured and ready" in message


def test_ensure_tailscale_already_ready_asks_nothing():
    def fake_which(_):
        return "/usr/bin/tailscale"

    def fake_run(cmd, **kwargs):
        if cmd[1] == "debug":
            return completed(stdout=json.dumps({"OperatorUser": connect.current_user()}))
        if cmd[1] == "funnel":
            return completed(stdout='{"Funnel": {"On": true}}')
        return completed(stdout=json.dumps({"BackendState": "Running"}))

    def unexpected_input(_):
        raise AssertionError("already-ready flow must not prompt")

    ready, message = connect.ensure_tailscale(
        which=fake_which, input_fn=unexpected_input, run=fake_run, print_fn=lambda _: None
    )
    assert ready
    assert "configured and ready" in message


def test_ensure_tailscale_aborts_when_install_declined():
    def fake_which(_):
        return None

    def fake_run(cmd, **kwargs):
        return completed()

    ready, message = connect.ensure_tailscale(
        which=fake_which, input_fn=lambda _: "n", run=fake_run, print_fn=lambda _: None
    )
    assert not ready
    assert "Install it" in message


def test_command_connect_ts_returns_zero_when_ready(monkeypatch, capsys):
    monkeypatch.setattr(connect, "ensure_tailscale", lambda: (True, "Funnel is configured and ready."))
    assert connect.command_connect_ts() == 0
    assert "TUNNEL_PROVIDER=tailscale gate" in capsys.readouterr().out


# ── CLI smoke test with a fake tailscale binary ─────────────────────────────


def _fake_tailscale_script(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "tailscale"
    script.write_text(
        '#!/bin/sh\n'
        'case "$1" in\n'
        '  status) echo \'{"BackendState":"Running"}\' ;;\n'
        '  debug) echo "{\"OperatorUser\":\"$(id -un)\"}" ;;\n'
        '  funnel) if [ "$2" = "status" ]; then echo \'{"Funnel":{"On":true}}\'; fi ;;\n'
        'esac\n'
        'exit 0\n',
        encoding="utf-8",
    )
    script.chmod(0o755)
    return bin_dir


def test_gate_connect_ts_warns_about_ignored_cf_flags(tmp_path):
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["GATE_ROOT"] = str(tmp_path / ".gate")
    env["GATE_PROJECT_DIR"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PATH"] = f"{_fake_tailscale_script(tmp_path)}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [sys.executable, "-m", "gate_cli", "connect", "ts", "--hostname", "mcp.example.com"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "apply only to 'gate connect cf'" in result.stdout


def test_gate_connect_ts_cli_smoke(tmp_path):
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["GATE_ROOT"] = str(tmp_path / ".gate")
    env["GATE_PROJECT_DIR"] = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["PATH"] = f"{_fake_tailscale_script(tmp_path)}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [sys.executable, "-m", "gate_cli", "connect", "ts"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Tailscale is ready" in result.stdout
    assert "TUNNEL_PROVIDER=tailscale gate" in result.stdout
