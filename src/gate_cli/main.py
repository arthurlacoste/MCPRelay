from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .clipboard import copy_text
from .config import read_env
from .changelog import version_notes
from .doctor import run_checks
from .logs import selected_logs
from .paths import GatePaths
from .state import load_state
from .uninstall import uninstall
from .updater import perform_update


def project_dir() -> Path:
    configured = os.environ.get("GATE_PROJECT_DIR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def version() -> str:
    return (project_dir() / "VERSION").read_text(encoding="utf-8").strip()


def paths() -> GatePaths:
    root = os.environ.get("GATE_ROOT")
    if root:
        gate_root = Path(root).expanduser()
        return GatePaths.from_home(gate_root.parent) if gate_root.name == ".gate" else GatePaths(
            root=gate_root,
            current=gate_root / "current",
            releases=gate_root / "releases",
            config=gate_root / "config",
            data=gate_root / "data",
            logs=gate_root / "logs",
            skills=gate_root / "skills",
            runtime=gate_root / "runtime",
            cache=gate_root / "cache",
            backups=gate_root / "backups",
            state=gate_root / "state.json",
        )
    return GatePaths.from_home(Path.home())



def gate_pid_file() -> Path:
    return Path(os.environ.get("GATE_PID_FILE", "/tmp/mcp_gateway.pid"))


def gate_is_running() -> bool:
    pid_file = gate_pid_file()
    if not pid_file.exists():
        return False
    try:
        services_pid = int(pid_file.read_text(encoding="utf-8").split(":", 1)[0])
        os.kill(services_pid, 0)
        return True
    except (OSError, ValueError):
        return False


def confirm_default_yes(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"", "y", "yes"}


def perform_gate_update(edge: bool, target_version: str | None = None) -> tuple[str, bool, str]:
    gate_paths = paths()
    state = load_state(gate_paths.state)
    current = state.active_version or version()
    updated, changed = perform_update(gate_paths, current, edge=edge, target_version=target_version)
    notes = version_notes(Path(updated.active_release) / "CHANGELOG.md", updated.active_version) if changed else ""
    return updated.active_version, changed, notes

def command_status() -> int:
    gate_paths = paths()
    state = load_state(gate_paths.state)
    env = read_env(gate_paths.config / ".env")
    print(f"Gate {state.active_version or version()}")
    print(f"Status: {'running' if gate_is_running() else 'stopped'}")
    print(f"Channel: {state.channel}")
    if state.active_release:
        print(f"Release: {state.active_release}")
    if env.get("MCP_BASE_URL"):
        print(f"Public MCP: {env['MCP_BASE_URL'].rstrip('/')}/mcp")
    return 0


def command_secret() -> int:
    secret = read_env(paths().config / ".env").get("OAUTH_ACCESS_SECRET", "")
    if not secret:
        print("No access secret configured.")
        return 1
    answer = input("This will reveal your Gate access secret. Continue? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Cancelled.")
        return 0
    copied = copy_text(secret)
    print(f"Access secret: {secret}")
    if copied:
        print("Secret copied to clipboard.")
    print("Keep this secret private.")
    return 0


def command_doctor() -> int:
    checks = run_checks(paths())
    for check in checks:
        print(f"{'✓' if check.ok else '✗'} {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def command_logs(*, gateway: bool, ngrok: bool, follow: bool) -> int:
    files = selected_logs(paths(), gateway=gateway, ngrok=ngrok)
    if not files:
        print("No matching logs found.")
        return 1
    if follow:
        return subprocess.run(["tail", "-f", *map(str, files)], check=False).returncode
    for path in files:
        print(f"==> {path} <==")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]
        print("\n".join(lines))
    return 0


def command_uninstall(*, purge: bool) -> int:
    prompt = "Type DELETE to permanently remove all Gate data: " if purge else "Uninstall Gate and keep config/data/logs/skills? [y/N] "
    answer = input(prompt).strip()
    if (purge and answer != "DELETE") or (not purge and answer.lower() not in {"y", "yes"}):
        print("Cancelled.")
        return 0
    uninstall(paths(), Path.home() / ".local" / "bin" / "gate", purge=purge)
    print("Gate uninstalled." if not purge else "Gate purged.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gate")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--noguard", action="store_true", help="disable command guards for this Gate launch only")
    sub = parser.add_subparsers(dest="command")
    for name in ("start", "stop", "restart", "status", "secret", "setup", "renew-secret", "rollback", "doctor"):
        sub.add_parser(name)
    logs = sub.add_parser("logs")
    logs.add_argument("--gateway", action="store_true")
    logs.add_argument("--ngrok", action="store_true")
    logs.add_argument("--follow", action="store_true")
    update = sub.add_parser("update")
    mode = update.add_mutually_exclusive_group()
    mode.add_argument("--edge", action="store_true")
    mode.add_argument("--stable", action="store_true")
    mode.add_argument("--version", dest="target_version", metavar="VERSION")
    uninstall_parser = sub.add_parser("uninstall")
    uninstall_parser.add_argument("--purge", action="store_true")
    return parser


def delegate_run_script(command: str | None = None, *, noguard: bool = False) -> int:
    script = project_dir() / "run.sh"
    if not script.exists():
        print(f"Missing launcher: {script}")
        return 1
    args = [str(script)] + ([command] if command else [])
    try:
        env = os.environ.copy()
        if noguard:
            env["MCP_COMMAND_GUARD_PROVIDER"] = "disabled"
            print("WARNING: command guard disabled for this launch.")
        return subprocess.run(args, cwd=project_dir(), env=env, check=False).returncode
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"Gate {version()}")
        return 0
    if args.command == "status": return command_status()
    if args.command == "secret": return command_secret()
    if args.command == "doctor": return command_doctor()
    if args.command == "logs": return command_logs(gateway=args.gateway, ngrok=args.ngrok, follow=args.follow)
    if args.command == "uninstall": return command_uninstall(purge=args.purge)
    if args.command == "update":
        from .release_flow import update_with_lifecycle
        try:
            result = update_with_lifecycle(
                is_running=gate_is_running,
                confirm=confirm_default_yes,
                stop=lambda: delegate_run_script("stop"),
                update=lambda: perform_gate_update(args.edge, args.target_version),
                start=lambda: delegate_run_script("start"),
            )
        except Exception as exc:
            from .migrations import MigrationError
            if isinstance(exc, MigrationError):
                print(f"Migration failed: {exc}")
                print(f"Report: {exc.report}")
                print(f"Create issue: {exc.issue_url}")
                return 1
            raise
        if result is None:
            print("Update cancelled.")
            return 0
        updated_version, changed, notes = result
        print(f"Gate {updated_version} is already installed." if not changed else f"Updated Gate to {updated_version}.")
        if notes:
            print("\nChanges:\n" + notes)
        return 0
    if args.command == "restart":
        stopped = delegate_run_script("stop")
        return stopped or delegate_run_script("start", noguard=args.noguard)
    if args.command == "rollback":
        from .updater import rollback_release
        was_running = gate_is_running()
        if was_running:
            if not confirm_default_yes("Gate is running. Stop it and continue? [Y/n] "):
                print("Rollback cancelled.")
                return 0
            if delegate_run_script("stop") != 0:
                return 1
        try:
            state = rollback_release(paths())
        except Exception:
            if was_running:
                delegate_run_script("start")
            raise
        if was_running and delegate_run_script("start") != 0:
            print("Rollback completed, but restart failed.")
            return 1
        print(f"Rolled back to Gate {state.active_version}")
        return 0
    if args.command in {"start", "stop", "setup", "renew-secret"}:
        return delegate_run_script(args.command, noguard=args.noguard)
    return delegate_run_script(noguard=args.noguard)
