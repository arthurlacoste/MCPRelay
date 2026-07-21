from __future__ import annotations

import ast
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol


Decision = Literal["allow", "deny"]


@dataclass(frozen=True)
class Remediation:
    summary: str
    commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class GuardRequest:
    tool_name: str
    arguments: Mapping[str, Any]
    command: str | None = None
    working_directory: str | None = None
    host: str | None = None
    platform: str | None = None


@dataclass(frozen=True)
class GuardResult:
    decision: Decision
    guard: str
    rule_id: str | None = None
    reason: str | None = None
    remediation: Remediation | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "decision": self.decision,
            "guard": self.guard,
            "rule": self.rule_id,
            "reason": self.reason,
        }
        if self.remediation:
            payload["remediation"] = {
                "summary": self.remediation.summary,
                "commands": list(self.remediation.commands),
            }
        return payload


class GuardProvider(Protocol):
    name: str

    def inspect(self, request: GuardRequest) -> GuardResult:
        ...


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    pattern: re.Pattern[str]
    reason: str
    summary: str
    commands: Callable[[re.Match[str], GuardRequest], tuple[str, ...]]


def _fixed(*commands: str) -> Callable[[re.Match[str], GuardRequest], tuple[str, ...]]:
    return lambda _match, _request: commands


def _rm_commands(match: re.Match[str], request: GuardRequest) -> tuple[str, ...]:
    target = match.groupdict().get("target") or "<target>"
    if target in {"/", "~", "$HOME", "${HOME}"}:
        return (f"test -e {shlex.quote(target)}", "Review the target and choose a non-system path")
    quoted = shlex.quote(target)
    return (
        f"test -e {quoted}",
        f'tar -czf "{target.rstrip("/")}-backup-$(date +%Y%m%d-%H%M%S).tar.gz" {quoted}',
        f"rm -rf {quoted}",
    )


class BuiltinGuardProvider:
    name = "builtin"

    def __init__(self) -> None:
        flags = re.IGNORECASE | re.MULTILINE
        self.rules = (
            _Rule("git.reset-hard", re.compile(r"\bgit\s+reset\s+--hard\b", flags), "This command may permanently discard uncommitted changes.", "Back up current changes before resetting.", _fixed('git status --short', 'git stash push --include-untracked -m "gate safety backup"', 'git reset --hard HEAD')),
            _Rule("git.clean-force", re.compile(r"\bgit\s+clean\s+-(?=[a-z]*f)(?=[a-z]*d)[a-z]+\b", flags), "This command permanently deletes untracked files and directories.", "Preview the deletion before cleaning.", _fixed("git clean -nd", "git clean -fd")),
            _Rule("git.checkout-discard", re.compile(r"\bgit\s+checkout\s+--(?:\s|$)", flags), "This command discards worktree changes.", "Back up changes before checkout.", _fixed("git status --short", 'git stash push --include-untracked -m "gate safety backup"')),
            _Rule("git.restore", re.compile(r"\bgit\s+restore\b(?![^;&|\n]*--staged\b)", flags), "This command may discard worktree changes.", "Back up changes before restoring files.", _fixed("git status --short", 'git stash push --include-untracked -m "gate safety backup"')),
            _Rule("git.branch-force-delete", re.compile(r"\bgit\s+branch\s+-D\b", flags), "This forcibly deletes a branch that may contain unmerged work.", "Inspect and create a backup branch first.", _fixed("git branch --show-current", "git log --oneline --decorate -10")),
            _Rule("git.stash-clear", re.compile(r"\bgit\s+stash\s+clear\b", flags), "This permanently deletes all stashes.", "Inspect and preserve needed stashes.", _fixed("git stash list")),
            _Rule("git.push-force", re.compile(r"\bgit\s+push\b(?=[^;&|\n]*\s--force(?:\s|$))(?![^;&|\n]*--force-with-lease)", flags), "Force push can overwrite remote history.", "Use lease protection instead.", _fixed("git push --force-with-lease")),
            _Rule("docker.system-prune", re.compile(r"\bdocker\s+system\s+prune\b", flags), "This removes unused Docker data across the system.", "Inventory Docker resources first.", _fixed("docker system df", "docker ps -a", "docker image ls")),
            _Rule("docker.volume-prune", re.compile(r"\bdocker\s+volume\s+prune\b", flags), "This deletes unused Docker volumes and their data.", "Identify and back up persistent volumes first.", _fixed("docker volume ls")),
            _Rule("docker.compose-down-volumes", re.compile(r"\bdocker(?:\s+compose|-compose)\s+down\b(?=[^;&|\n]*(?:\s-v\b|--volumes\b))", flags), "This removes compose volumes and persistent data.", "Inspect services and volumes before shutdown.", _fixed("docker compose ps", "docker volume ls", "docker compose down")),
            _Rule("database.destructive-sql", re.compile(r"\b(?:DROP\s+(?:DATABASE|TABLE|SCHEMA)|TRUNCATE\s+(?:TABLE\s+)?|DELETE\s+FROM\s+\S+)", flags), "This SQL operation can permanently destroy data.", "Verify the server and database, create a backup, and validate it before retrying.", _fixed("pg_dump --format=custom --file=database.backup <database>", "pg_restore --list database.backup")),
            _Rule("kubernetes.delete-namespace", re.compile(r"\bkubectl\s+delete\s+(?:namespace|ns)\b", flags), "Deleting a namespace removes all resources in it.", "Verify the cluster context and namespace contents.", _fixed("kubectl config current-context", "kubectl get namespace <namespace>", "kubectl get all --namespace <namespace>")),
            _Rule("terraform.destroy", re.compile(r"\bterraform\s+destroy\b", flags), "Terraform destroy removes managed infrastructure.", "Create and review a destroy plan first.", _fixed("terraform plan -destroy -out=destroy.plan", "terraform show destroy.plan", "terraform destroy")),
            _Rule("filesystem.format", re.compile(r"(?:^|[;&|]\s*|\b)(?:mkfs(?:\.\w+)?|format\s+[a-z]:|Format-Volume\b|Clear-Disk\b|diskpart\b|wipefs\b)", flags), "This command can erase a filesystem or disk.", "Verify the device identity and create a validated backup before formatting.", _fixed("lsblk", "Review the target device and mounted filesystems")),
            _Rule("powershell.remove-recursive", re.compile(r"\b(?:Remove-Item|rm|del|rd|ri)\b(?=[^;|\n]*-(?:Recurse|r)\b)(?![^;|\n]*-WhatIf\b)", flags), "Recursive PowerShell deletion can permanently remove data.", "Preview the target with WhatIf and back it up.", _fixed("Remove-Item -Recurse -WhatIf <path>")),
            _Rule("windows.wsl-unregister", re.compile(r"\bwsl(?:\.exe)?\s+--unregister\b", flags), "Unregistering a WSL distribution permanently deletes it.", "Export the distribution before unregistering it.", _fixed("wsl --list --verbose", "wsl --export <distribution> <backup.tar>")),
            _Rule("windows.recursive-delete", re.compile(r"(?:^|[&|]\s*)(?:rd|rmdir|del)\s+(?=[^\n]*\/s\b)", flags), "Recursive Windows deletion can permanently remove data.", "Verify and back up the target first.", _fixed("dir <path>")),
            _Rule("filesystem.rm-recursive-force", re.compile(r"\bxargs\b[^|;&\n]*\brm\s+-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\b", flags), "Recursive forced deletion through xargs can permanently remove data.", "Review matched paths before deletion.", _fixed("Review the producer output without xargs")),
            _Rule("filesystem.rm-recursive-force", re.compile(r"(?:^|[;&|]\s*|\$\(|`|['\"]|\b(?:bash|sh|zsh)\s+-c\s+['\"]|\bssh\s+\S+\s+['\"])(?:sudo\s+)?rm\s+-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\s+(?P<target>[^;&|\n'\")`]+)", flags), "Recursive forced deletion can permanently remove data.", "Verify and back up the target before deletion.", _rm_commands),
        )

    def inspect(self, request: GuardRequest) -> GuardResult:
        command = self._normalize(request.command or "")
        embedded = self._embedded_python(command)
        if embedded:
            nested = self.inspect(GuardRequest(request.tool_name, request.arguments, embedded, request.working_directory, request.host, request.platform))
            if nested.decision == "deny":
                return nested
        elif re.match(r"^python\d*(?:\.\d+)?\s+-c\b", command.strip(), re.IGNORECASE):
            return GuardResult("allow", self.name)
        if re.search(r"\|\s*(?:sh|bash|zsh|pwsh|powershell|cmd|psql|mysql|sqlite3)(?:\.exe)?\b", command, re.IGNORECASE) and re.search(r"(?:^|\|)\s*(?:grep|rg)\b", command, re.IGNORECASE):
            return GuardResult("deny", self.name, "shell.executable-pipeline", "A filtered pipeline is being executed by a shell or database client.", Remediation("Inspect and save the filtered output before executing it.", ("Run the pipeline without the final execution stage",)))
        if self._is_data_only(command):
            return GuardResult("allow", self.name)
        for rule in self.rules:
            match = rule.pattern.search(command)
            if match:
                rule_id = rule.rule_id
                if rule_id == "filesystem.rm-recursive-force" and self._is_root_or_home(match, request):
                    rule_id = "filesystem.root-home-delete"
                return GuardResult("deny", self.name, rule_id, rule.reason, Remediation(rule.summary, rule.commands(match, request)))
        return GuardResult("allow", self.name)

    @staticmethod
    def _normalize(command: str) -> str:
        command = re.sub(r"(?<![\w.-])(?:[A-Za-z]:[\\/]|/)(?:[^\s'\";&|]+[\\/])+(?=(?:rm|git|docker|kubectl|terraform|mkfs)(?:\.exe)?\b)", "", command, flags=re.IGNORECASE)
        command = re.sub(r"(?:^|[;&|]\s*)(?:(?:sudo|command|nohup)\s+)*(?:env(?:\s+\w+=\S+)*\s+)?(?:busybox\s+)?", lambda match: match.group(0)[-2:] if match.group(0).rstrip().endswith(tuple(";&|")) else "", command, flags=re.IGNORECASE)
        command = re.sub(r"\bgit\s+(?:-C\s+\S+\s+)+", "git ", command, flags=re.IGNORECASE)
        command = re.sub(r"\brm\s+--recursive\s+--force\b|\brm\s+--force\s+--recursive\b", "rm -rf", command, flags=re.IGNORECASE)
        command = re.sub(r"\bgit\s+clean\s+(?:--force|-f)\s+(?:--directories|-d)\b", "git clean -fd", command, flags=re.IGNORECASE)
        command = re.sub(r"\bgit\s+push\s+-f\b", "git push --force", command, flags=re.IGNORECASE)
        return command

    @staticmethod
    def _embedded_python(command: str) -> str | None:
        match = re.match(r"^python\d*(?:\.\d+)?\s+-c\s+(.+)$", command.strip(), re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        try:
            source = ast.literal_eval(match.group(1))
        except (ValueError, SyntaxError):
            return None
        if not isinstance(source, str):
            return None
        candidates = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                name = ""
                if isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    name = node.func.id
                if name in {"system", "popen", "run", "call", "check_call", "check_output"}:
                    candidates.append(node.args[0].value)
        return " ; ".join(candidates) if candidates else None

    @staticmethod
    def _is_data_only(command: str) -> bool:
        stripped = command.strip()
        if re.match(r"^(?:echo|printf)\b", stripped, re.IGNORECASE):
            if re.search(r"\|\s*(?:xargs\s+)?(?:sh|bash|zsh|pwsh|powershell|cmd|psql|mysql|sqlite3)(?:\.exe)?\b", stripped, re.IGNORECASE):
                return False
            return not re.search(r"(?:&&|\|\||;|>|<|\$\(|`)", stripped)
        if re.search(r"(?:^|\|)\s*(?:grep|rg)\b", stripped, re.IGNORECASE):
            return not re.search(r"\|\s*(?:sh|bash|zsh|pwsh|powershell|cmd|psql|mysql|sqlite3)(?:\.exe)?\b|(?:&&|\|\||;|>|\$\(|`)", stripped, re.IGNORECASE)
        return False

    @staticmethod
    def _is_root_or_home(match: re.Match[str], request: GuardRequest) -> bool:
        target = (match.groupdict().get("target") or "").strip()
        if target in {"/", "/*", "~", "~/", "$HOME", "${HOME}"}:
            return True
        if target not in {".", "./"}:
            return False
        cwd = Path(request.working_directory or os.getcwd()).expanduser().resolve()
        return cwd == Path(cwd.anchor) or cwd == Path.home().resolve()


class DcgGuardProvider:
    name = "dcg"

    def __init__(self, executable: str = "dcg", timeout_seconds: float = 1.0, expected_version: str | None = None) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.expected_version = expected_version
        self._verified_executable: str | None = None

    def inspect(self, request: GuardRequest) -> GuardResult:
        executable = shutil.which(self.executable)
        if not executable:
            raise RuntimeError("dcg executable is unavailable")
        if executable != self._verified_executable:
            version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=self.timeout_seconds, check=False, shell=False)
            if version.returncode != 0 or (self.expected_version and self.expected_version not in version.stdout + version.stderr):
                raise RuntimeError("dcg executable version verification failed")
            self._verified_executable = executable
        completed = subprocess.run(
            [executable, "test", "--format", "json", request.command or ""],
            cwd=request.working_directory,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
            shell=False,
            env={**os.environ, "DCG_FAIL_CLOSED": "1", "DCG_COLOR": "never"},
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError("dcg returned an invalid exit status")
        try:
            payload = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RuntimeError("dcg returned invalid output") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("decision"), str):
            raise RuntimeError("dcg returned an invalid schema")
        for key in ("reason", "explanation", "suggestion", "rule_id", "rule", "pack_id", "pack"):
            if key in payload and payload[key] is not None and not isinstance(payload[key], str):
                raise RuntimeError("dcg returned an invalid schema")
        decision = payload["decision"].lower()
        if decision in {"block", "blocked", "deny", "denied"}:
            rule = payload.get("rule_id") or payload.get("rule")
            pack = payload.get("pack_id") or payload.get("pack")
            rule_id = f"{pack}:{rule}" if pack and rule else str(rule or pack or "dcg.denied")
            reason = str(payload.get("reason") or payload.get("explanation") or "dcg denied this command")
            remediation_payload = payload.get("remediation")
            suggestion = str(payload.get("suggestion") or (remediation_payload.get("summary") if isinstance(remediation_payload, dict) else None) or "Review the command and use a safer sequence.")
            raw_commands = payload.get("commands") or payload.get("safe_commands")
            if raw_commands is None and isinstance(remediation_payload, dict):
                raw_commands = remediation_payload.get("commands")
            if raw_commands is None:
                commands = ()
            elif isinstance(raw_commands, list) and all(isinstance(item, str) for item in raw_commands):
                commands = tuple(raw_commands)
            else:
                raise RuntimeError("dcg returned invalid remediation commands")
            return GuardResult("deny", self.name, rule_id, reason, Remediation(suggestion, commands))
        if decision not in {"allow", "allowed"} or completed.returncode != 0:
            raise RuntimeError("dcg returned an invalid decision")
        return GuardResult("allow", self.name)


class DisabledGuardProvider:
    name = "disabled"

    def inspect(self, request: GuardRequest) -> GuardResult:
        return GuardResult("allow", self.name)


class GuardService:
    def __init__(self, provider: str = "builtin", fallback: str = "builtin", event_logger: Callable[[str, dict[str, Any]], None] | None = None, dcg_executable: str = "dcg", dcg_version: str | None = None) -> None:
        self.provider_name = provider.lower()
        self.fallback_name = fallback.lower()
        self.event_logger = event_logger
        self.providers: dict[str, GuardProvider] = {
            "builtin": BuiltinGuardProvider(),
            "dcg": DcgGuardProvider(dcg_executable, expected_version=dcg_version or "0.6.7"),
            "disabled": DisabledGuardProvider(),
        }
        if self.provider_name not in self.providers or self.fallback_name not in self.providers:
            raise ValueError("guard provider must be builtin, dcg, or disabled")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str], event_logger=None) -> "GuardService":
        return cls(environ.get("MCP_COMMAND_GUARD_PROVIDER", "builtin"), environ.get("MCP_COMMAND_GUARD_FALLBACK", "builtin"), event_logger, environ.get("MCP_DCG_EXECUTABLE", "dcg"), environ.get("MCP_DCG_VERSION"))

    def inspect(self, request: GuardRequest) -> GuardResult:
        try:
            result = self.providers[self.provider_name].inspect(request)
        except Exception as exc:
            if self.event_logger:
                self.event_logger("command_guard_provider_failure", {"guard": self.provider_name, "error": type(exc).__name__})
            if self.fallback_name == self.provider_name:
                return GuardResult("deny", self.provider_name, "guard.provider-failure", "The configured command guard could not inspect this request.", Remediation("Retry after restoring the command guard."))
            result = self.providers[self.fallback_name].inspect(request)
        if self.event_logger:
            self.event_logger("command_guard_decision", {
                "tool": request.tool_name,
                "host": request.host,
                "working_directory": request.working_directory,
                "platform": request.platform,
                "decision": result.decision,
                "guard": result.guard,
                "rule": result.rule_id,
                "reason": result.reason,
                "remediation": result.remediation.summary if result.remediation else None,
            })
        return result


from secret_redactor import SecretRedactor

def current_guard_request(tool_name: str, arguments: Mapping[str, Any], command: str, cwd: str | None = None, host: str | None = None) -> GuardRequest:
    resolved = str(Path(cwd).expanduser().resolve()) if cwd else os.getcwd()
    return GuardRequest(tool_name, arguments, command, resolved, host, platform.system())
