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


# ── Status / login ──────────────────────────────────────────────────────────


def test_tailscale_status_parses_running_session():
    run = lambda *a, **k: completed(stdout=json.dumps({"BackendState": "Running"}))
    assert connect.tailscale_status(run=run)["BackendState"] == "Running"


def test_tailscale_status_reports_failed_daemon():
    run = lambda *a, **k: completed(code=1, stderr="no state")
    assert "not authenticated" in connect.tailscale_status(run=run)["error"]


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
