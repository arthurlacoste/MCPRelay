import os
import subprocess
import sys
from pathlib import Path

from gate_cli.paths import GatePaths
from gate_cli.state import GateState, save_state


def run_cli(tmp_path: Path, *args: str, input_text: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["GATE_PROJECT_DIR"] = str(Path(__file__).resolve().parents[1])
    return subprocess.run(
        [sys.executable, "-m", "gate_cli", *args],
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def test_version_reads_root_version_file(tmp_path):
    result = run_cli(tmp_path, "--version")
    assert result.returncode == 0
    assert result.stdout.strip() == "Gate 0.1.2"


def test_status_never_prints_access_secret(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    (paths.config / ".env").write_text(
        "MCP_BASE_URL=https://demo.ngrok.app\nOAUTH_ACCESS_SECRET=super-secret\n",
        encoding="utf-8",
    )
    save_state(paths.state, GateState(active_version="0.1.0", active_release="/tmp/v0.1.0"))

    result = run_cli(tmp_path, "status")

    assert result.returncode == 0
    assert "Gate 0.1.0" in result.stdout
    assert "https://demo.ngrok.app" in result.stdout
    assert "super-secret" not in result.stdout


def test_secret_requires_confirmation_then_reveals_value(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    (paths.config / ".env").write_text("OAUTH_ACCESS_SECRET=super-secret\n", encoding="utf-8")

    refused = run_cli(tmp_path, "secret", input_text="n\n")
    accepted = run_cli(tmp_path, "secret", input_text="y\n")

    assert "super-secret" not in refused.stdout
    assert accepted.returncode == 0
    assert "super-secret" in accepted.stdout

def test_default_command_delegates_to_run_script(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    run_script = project / "run.sh"
    run_script.write_text("#!/usr/bin/env bash\nprintf 'delegated:%s\\n' \"$*\"\n")
    run_script.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["GATE_PROJECT_DIR"] = str(project)

    result = subprocess.run([sys.executable, "-m", "gate_cli"], env=env, text=True, capture_output=True)

    assert result.returncode == 0
    assert result.stdout.strip() == "delegated:"


def test_start_and_stop_delegate_to_run_script(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    run_script = project / "run.sh"
    run_script.write_text("#!/usr/bin/env bash\nprintf 'delegated:%s\\n' \"$*\"\n")
    run_script.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["GATE_PROJECT_DIR"] = str(project)

    started = subprocess.run([sys.executable, "-m", "gate_cli", "start"], env=env, text=True, capture_output=True)
    stopped = subprocess.run([sys.executable, "-m", "gate_cli", "stop"], env=env, text=True, capture_output=True)

    assert started.stdout.strip() == "delegated:start"
    assert stopped.stdout.strip() == "delegated:stop"

def test_doctor_command_prints_checks(tmp_path):
    result = run_cli(tmp_path, "doctor")
    assert "current release" in result.stdout
    assert result.returncode == 1


def test_logs_command_reads_gateway_log(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    log = paths.logs / "services" / "gateway.log"
    log.parent.mkdir()
    log.write_text("hello gateway\n")

    result = run_cli(tmp_path, "logs", "--gateway")

    assert result.returncode == 0
    assert "hello gateway" in result.stdout


def test_uninstall_requires_confirmation(tmp_path):
    paths = GatePaths.from_home(tmp_path)
    paths.ensure_persistent()
    (paths.releases / "v0.1.0").mkdir()

    result = run_cli(tmp_path, "uninstall", input_text="n\n")

    assert result.returncode == 0
    assert paths.releases.exists()

def test_update_parser_accepts_edge_and_stable_modes():
    from gate_cli.main import build_parser
    assert build_parser().parse_args(["update", "--edge"]).edge
    assert build_parser().parse_args(["update", "--stable"]).stable

def test_update_command_uses_lifecycle_helpers(monkeypatch, tmp_path, capsys):
    import gate_cli.main as main_module
    events = []
    monkeypatch.setattr(main_module, "gate_is_running", lambda: True)
    monkeypatch.setattr(main_module, "confirm_default_yes", lambda prompt: events.append("confirm") or True)
    monkeypatch.setattr(main_module, "delegate_run_script", lambda command=None: events.append(command or "interactive") or 0)
    monkeypatch.setattr(main_module, "perform_gate_update", lambda edge, stable: ("0.2.0", True, "- New CLI"))

    assert main_module.main(["update"]) == 0
    assert events == ["confirm", "stop", "start"]
    assert "New CLI" in capsys.readouterr().out

def test_status_reports_running_when_pid_is_alive(monkeypatch, tmp_path, capsys):
    import gate_cli.main as main_module
    monkeypatch.setattr(main_module, "gate_is_running", lambda: True)
    monkeypatch.setattr(main_module, "paths", lambda: GatePaths.from_home(tmp_path))
    GatePaths.from_home(tmp_path).ensure_persistent()
    assert main_module.command_status() == 0
    assert "Status: running" in capsys.readouterr().out


def test_update_migration_error_prints_report_and_issue(monkeypatch, capsys, tmp_path):
    import gate_cli.main as main_module
    from gate_cli.migrations import MigrationError
    report = tmp_path / "report.log"
    report.write_text("traceback")
    error = MigrationError("boom", report, "https://github.com/arthurlacoste/gate/issues/new?x=1")
    monkeypatch.setattr(main_module, "gate_is_running", lambda: False)
    monkeypatch.setattr(main_module, "perform_gate_update", lambda edge, stable: (_ for _ in ()).throw(error))

    assert main_module.main(["update"]) == 1
    output = capsys.readouterr().out
    assert str(report) in output
    assert "issues/new" in output


def test_rollback_running_gate_prompts_stop_and_restart(monkeypatch, tmp_path):
    import gate_cli.main as main_module
    from gate_cli.state import GateState
    events = []
    monkeypatch.setattr(main_module, "gate_is_running", lambda: True)
    monkeypatch.setattr(main_module, "confirm_default_yes", lambda prompt: events.append("confirm") or True)
    monkeypatch.setattr(main_module, "delegate_run_script", lambda command=None: events.append(command) or 0)
    monkeypatch.setattr("gate_cli.updater.rollback_release", lambda paths: GateState(active_version="0.1.0"))

    assert main_module.main(["rollback"]) == 0
    assert events == ["confirm", "stop", "start"]
