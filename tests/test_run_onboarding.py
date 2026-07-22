import os
import pty
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


RUN_SCRIPT = Path(__file__).resolve().parents[1] / "run.sh"
VENV_PYTHON = Path(sys.executable)
INTERACTIVE_LAUNCHER = RUN_SCRIPT.parent / "src" / "interactive_launcher.py"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _sandbox(tmp_path: Path, env_content: str) -> tuple[Path, dict[str, str]]:
    script = tmp_path / "run.sh"
    shutil.copy2(RUN_SCRIPT, script)
    shutil.copy2(RUN_SCRIPT.parent / "requirements.txt", tmp_path / "requirements.txt")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".env").write_text(env_content)
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    _write_executable(
        tmp_path / ".venv" / "bin" / "python",
        f'#!/usr/bin/env bash\nexec "{VENV_PYTHON}" "$@"\n',
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "ngrok",
        "#!/usr/bin/env bash\n"
        'if [ "${1:-} ${2:-}" = "config check" ]; then exit 0; fi\n'
        'if [ "${1:-}" = "http" ]; then exec sleep 30; fi\n',
    )
    _write_executable(
        fake_bin / "curl",
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' "
        "'{\"tunnels\":[{\"proto\":\"https\",\"public_url\":\"https://fresh.ngrok-free.app\"}]}'\n",
    )
    _write_executable(fake_bin / "pgrep", "#!/usr/bin/env bash\nexit 1\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GATE_PID_FILE"] = str(tmp_path / "mcp_gateway.pid")
    env["MCP_CONFIG_ROOT"] = str(tmp_path / "config")
    env["MCP_LOG_ROOT"] = str(tmp_path / "logs")
    env.pop("GATE_PROJECT_DIR", None)
    env.pop("GATE_ROOT", None)
    return script, env


def _enable_interactive_fakes(tmp_path: Path) -> None:
    venv_bin = tmp_path / ".venv" / "bin"
    assert INTERACTIVE_LAUNCHER.exists(), "interactive supervisor missing"
    (tmp_path / "src").mkdir()
    shutil.copy2(INTERACTIVE_LAUNCHER, tmp_path / "src" / "interactive_launcher.py")
    (tmp_path / "start_services.py").write_text(
        "import signal, json, threading\n"
        "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
        "class H(BaseHTTPRequestHandler):\n"
        "    def do_GET(self):\n"
        "        self.send_response(200)\n"
        "        self.send_header('Content-Type','application/json')\n"
        "        self.end_headers()\n"
        "        self.wfile.write(json.dumps({'ok':True}).encode())\n"
        "    def log_message(self, *a): pass\n"
        "def run(port):\n"
        "    s = HTTPServer(('0.0.0.0', port), H)\n"
        "    while True: s.handle_request()\n"
        "for p in (8761, 4040):\n"
        "    threading.Thread(target=run, args=(p,), daemon=True).start()\n"
        "def stop(*_): raise SystemExit(0)\n"
        "signal.signal(signal.SIGINT, stop)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "import time\n"
        "while True: time.sleep(1)\n"
    )
    (venv_bin / "activate").write_text(f'export PATH="{venv_bin}:$PATH"\n')


def _read_pty_until(fd: int, expected: bytes, timeout: float) -> bytes:
    output = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.1)
        if not readable:
            continue
        try:
            output += os.read(fd, 4096)
        except OSError:
            break
        if expected in output:
            return output
    raise AssertionError(f"Timed out waiting for {expected!r}. Output: {output!r}")


def test_run_script_bootstraps_python_before_onboarding():
    content = RUN_SCRIPT.read_text()

    interactive = content[content.index("run_interactive()") : content.index("start_daemon()")]
    daemon = content[content.index("start_daemon()") : content.index("stop_daemon()")]

    assert interactive.index("ensure_python_environment") < interactive.index("ensure_onboarding")
    assert daemon.index("ensure_python_environment") < daemon.index("ensure_onboarding")
    assert "setup)   ensure_python_environment; ensure_onboarding ;;" in content
    assert "renew-secret) ensure_python_environment; ensure_onboarding true ;;" in content


def test_interactive_launch_reports_existing_live_daemon(tmp_path):
    script, env = _sandbox(
        tmp_path,
        "MCP_BASE_URL=https://stable.example\n"
        "OAUTH_ACCESS_SECRET=readable-secret\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$valid\n",
    )
    Path(env["GATE_PID_FILE"]).write_text(f"{os.getpid()}:{os.getpid()}\n")

    result = subprocess.run(
        [str(script)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"Gate already running (PID {os.getpid()})" in result.stdout
    assert "Daemon PID file exists" not in result.stderr
    assert "ngrok inspector" in result.stdout


def test_interactive_launch_removes_stale_pid_file(tmp_path):
    content = RUN_SCRIPT.read_text()
    definitions = content[: content.index('parse_runtime_args "$@"')]
    harness = tmp_path / "reconcile.sh"
    _write_executable(
        harness,
        definitions
        + "\nif reconcile_pid_file; then exit 9; fi\n"
        + '[ ! -e "$PID_FILE" ]\n',
    )
    pid_file = tmp_path / "stale.pid"
    pid_file.write_text("99999999:99999998\n")
    env = os.environ.copy()
    env["GATE_PID_FILE"] = str(pid_file)

    result = subprocess.run(
        [str(harness)], env=env, text=True, capture_output=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert "Removing stale daemon PID file" in result.stdout
    assert not pid_file.exists()


def test_python_bootstrap_uses_canonical_requirements():
    content = RUN_SCRIPT.read_text()

    assert 'find_compatible_python' in content
    assert '"$python_bin" -m venv "$PROJECT_DIR/.venv"' in content
    assert '"$python" -m pip install -r "$requirements"' in content
    assert "pip install argon2-cffi" not in content


def test_run_script_onboards_before_starting_services():
    content = RUN_SCRIPT.read_text()

    interactive = content.index("run_interactive()")
    daemon = content.index("start_daemon()")

    assert content.index("ensure_onboarding", interactive) < content.index(
        "interactive_launcher.py", interactive
    )
    assert content.index("ensure_onboarding", daemon) < content.index(
        "nohup python3 start_services.py", daemon
    )


def test_running_modes_cleanup_ngrok_before_starting_services():
    content = RUN_SCRIPT.read_text()
    interactive = content[content.index("run_interactive()") : content.index("start_daemon()")]
    daemon = content[content.index("start_daemon()") : content.index("stop_daemon()")]

    assert interactive.index("cleanup_stale_ngrok") < interactive.index("interactive_launcher.py")
    assert daemon.index("cleanup_stale_ngrok") < daemon.index("nohup python3 start_services.py")


def test_ngrok_cleanup_escalates_and_verifies_process_exit(tmp_path):
    content = RUN_SCRIPT.read_text()
    definitions = content[: content.index('parse_runtime_args "$@"')]
    harness = tmp_path / "cleanup.sh"
    _write_executable(harness, definitions + "\ncleanup_stale_ngrok\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pid_file = tmp_path / "pids"
    _write_executable(
        fake_bin / "pgrep",
        "#!/usr/bin/env bash\n"
        "while IFS= read -r pid; do\n"
        "  state=$(ps -o stat= -p \"$pid\" 2>/dev/null || true)\n"
        "  case \"$state\" in ''|*Z*) ;; *) printf '%s\\n' \"$pid\" ;; esac\n"
        "done < \"$FAKE_PIDS\"\n",
    )
    stubborn = subprocess.Popen(
        [
            VENV_PYTHON,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(30)",
        ],
        text=True,
        stdout=subprocess.PIPE,
    )
    assert stubborn.stdout.readline().strip() == "ready"
    pid_file.write_text(f"{stubborn.pid}\n")
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["FAKE_PIDS"] = str(pid_file)

    try:
        result = subprocess.run(
            [str(harness)],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "Forcing stale ngrok processes" in result.stdout
        assert stubborn.wait(timeout=2) < 0
    finally:
        if stubborn.poll() is None:
            stubborn.kill()
            stubborn.wait()


def test_onboarding_creates_default_skills_directory_for_complete_config(tmp_path):
    script, env = _sandbox(
        tmp_path,
        "MCP_BASE_URL=https://stable.example\n"
        "OAUTH_ACCESS_SECRET=readable-secret\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$valid\n",
    )
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)

    result = subprocess.run(
        [str(script), "setup"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (home / ".gate" / "skills").is_dir()


def test_onboarding_creates_configured_skills_directory(tmp_path):
    custom_root = tmp_path / "custom" / "skills"
    script, env = _sandbox(
        tmp_path,
        "MCP_BASE_URL=https://stable.example\n"
        "OAUTH_ACCESS_SECRET=readable-secret\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$valid\n"
        f"MCP_SKILLS_ROOT={custom_root}\n",
    )

    result = subprocess.run(
        [str(script), "setup"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert custom_root.is_dir()


def test_onboarding_persists_url_secret_and_hash():
    content = RUN_SCRIPT.read_text()

    assert 'OAUTH_ACCESS_SECRET "$access_secret"' in content
    assert 'OAUTH_ACCESS_SECRET_HASH "$access_hash"' in content
    assert 'MCP_BASE_URL "$public_url"' in content
    assert 'chmod 600 "$CONFIG_FILE"' in content


def test_onboarding_reuses_complete_configuration():
    content = RUN_SCRIPT.read_text()

    assert '[ -n "$public_url" ] && [ -n "$access_secret" ]' in content
    assert '[[ "$access_hash" == \\$argon2id\\$* ]]' in content


def test_setup_and_secret_renewal_commands_are_available():
    content = RUN_SCRIPT.read_text()

    assert "setup)   ensure_python_environment; ensure_onboarding ;;" in content
    assert "renew-secret) ensure_python_environment; ensure_onboarding true ;;" in content


def test_runtime_flags_are_ephemeral_and_forwarded_to_children():
    content = RUN_SCRIPT.read_text()

    assert '--widget' in content
    assert '--realtime' in content
    assert 'export MCP_WIDGET_ENABLED=true' in content
    assert 'export MCP_REALTIME_STATUS_ENABLED=true' in content
    assert 'set_env_values MCP_WIDGET_ENABLED' not in content


def test_interactive_mode_uses_python_supervisor():
    content = RUN_SCRIPT.read_text()
    interactive = content[content.index("run_interactive()") : content.index("start_daemon()")]

    assert '"$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/src/interactive_launcher.py"' in interactive
    assert "read -r -s -n 1" not in interactive
    assert "trap 'exit 0' INT TERM" not in interactive


def test_ngrok_inspector_is_shown_for_running_modes():
    content = RUN_SCRIPT.read_text()
    launcher = INTERACTIVE_LAUNCHER.read_text()

    assert 'NGROK_INSPECT_URL="http://127.0.0.1:4040"' in content
    assert content.count("show_ngrok_inspector") == 4
    assert 'NGROK_INSPECT_URL = "http://127.0.0.1:4040"' in launcher


def test_vision_banner_is_shown_at_script_start():
    content = RUN_SCRIPT.read_text()

    assert "oooooo     oooo ooooo  .oooooo..o" in content
    assert "formerly Gate, made with <3 by arthak" in content
    assert "printf '\\033[2J\\033[H'" in content
    assert content.index("clear_screen\nshow_banner\n\ncase") < content.index('case "${1:-}"')


def test_setup_repairs_missing_secret_without_touching_other_values(tmp_path):
    script, env = _sandbox(
        tmp_path,
        "KEEP_ME=yes\n"
        "MCP_BASE_URL=https://old.example\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$old\n",
    )

    result = subprocess.run(
        [str(script), "setup"],
        cwd=tmp_path.parent,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    config = (tmp_path / "config" / ".env").read_text()
    assert "KEEP_ME=yes" in config
    assert "MCP_BASE_URL=https://fresh.ngrok-free.app" in config
    assert "OAUTH_ACCESS_SECRET=" in config
    assert "OAUTH_ACCESS_SECRET_HASH=$argon2id$" in config
    assert "# Rotate OAuth access secret: ./run.sh renew-secret" in config
    assert stat.S_IMODE((tmp_path / "config" / ".env").stat().st_mode) == 0o600
    assert "Access secret:" in result.stdout
    assert "ngrok inspector: http://127.0.0.1:4040" in result.stdout


def test_renew_secret_reuses_url_and_prints_new_secret(tmp_path):
    script, env = _sandbox(
        tmp_path,
        "MCP_BASE_URL=https://stable.example\n"
        "OAUTH_ACCESS_SECRET=old-readable-secret\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$old\n",
    )

    result = subprocess.run(
        [str(script), "renew-secret"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    config = (tmp_path / "config" / ".env").read_text()
    assert "MCP_BASE_URL=https://stable.example" in config
    assert "OAUTH_ACCESS_SECRET=old-readable-secret" not in config
    assert "Access secret:" in result.stdout


def test_ctrl_c_exits_after_interactive_startup(tmp_path):
    script, env = _sandbox(
        tmp_path,
        "MCP_BASE_URL=https://stable.example\n"
        "OAUTH_ACCESS_SECRET=readable-secret\n"
        "OAUTH_ACCESS_SECRET_HASH=$argon2id$valid\n",
    )
    _enable_interactive_fakes(tmp_path)

    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(tmp_path)
        os.execve(str(script), [str(script)], env)

    try:
        _read_pty_until(fd, b"ngrok inspector", 15)
        os.write(fd, b"\x03")

        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            readable, _, _ = select.select([fd], [], [], 0)
            if readable:
                try:
                    os.read(fd, 4096)
                except OSError:
                    pass
            exited_pid, _ = os.waitpid(pid, os.WNOHANG)
            if exited_pid == pid:
                break
            time.sleep(0.1)
        else:
            raise AssertionError("run.sh did not exit within 8 seconds after Ctrl+C")
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        time.sleep(0.2)
        try:
            remaining_pid, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            remaining_pid = pid
        if remaining_pid == 0:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
        os.close(fd)

def test_onboarding_reuses_detected_ngrok_process():
    content = RUN_SCRIPT.read_text()
    launcher = INTERACTIVE_LAUNCHER.read_text()

    assert 'export GATE_EXISTING_NGROK_PID="$ONBOARDING_NGROK_PID"' in content
    assert 'GATE_EXISTING_NGROK_PID' in launcher
    onboarding = content[content.index('open_temporary_ngrok()'):content.index('ensure_onboarding()')]
    assert 'kill "$temp_pid"' not in onboarding

def test_onboarding_copies_generated_secret_when_clipboard_exists():
    content = RUN_SCRIPT.read_text()
    assert "copy_access_secret" in content
    assert "Secret copied to clipboard." in content


def test_stop_cleans_gateway_port_without_pid_file():
    content = RUN_SCRIPT.read_text()
    stop = content[content.index("gateway_port_pids()") : content.index("status()")]

    assert 'fuser -n tcp "$NGROK_PORT"' in stop
    assert 'lsof -nP -tiTCP:"$NGROK_PORT" -sTCP:LISTEN' in stop
    assert 'ss -ltnp "sport = :$NGROK_PORT"' in stop
    assert 'pkill "-$signal" -f "$PROJECT_DIR/src/mcp_gateway.py"' in stop
    assert 'pkill "-$signal" -f "$PROJECT_DIR/start_services.py"' in stop
    assert 'fuser -k "-$signal" "$NGROK_PORT/tcp"' in stop
    assert "signal_gateway_processes TERM" in stop
    assert "signal_gateway_processes KILL" in stop
    assert 'if [ ! -f "$PID_FILE" ]' not in stop
    assert 'sudo fuser -k -9 $NGROK_PORT/tcp' in stop
