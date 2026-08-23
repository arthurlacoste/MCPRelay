import json
import os
from pathlib import Path

import pytest

from command_guard import (
    BuiltinGuardProvider,
    DcgGuardProvider,
    GuardRequest,
    GuardService,
    SecretRedactor,
)


@pytest.mark.parametrize(("command", "rule"), [
    ("rm -rf ./data", "filesystem.rm-recursive-force"),
    ("rm -rf /", "filesystem.root-home-delete"),
    ("git reset --hard HEAD", "git.reset-hard"),
    ("git clean -fd", "git.clean-force"),
    ("git checkout -- src", "git.checkout-discard"),
    ("git restore src", "git.restore"),
    ("git branch -D old", "git.branch-force-delete"),
    ("git stash clear", "git.stash-clear"),
    ("git push --force origin main", "git.push-force"),
    ("docker system prune", "docker.system-prune"),
    ("docker volume prune", "docker.volume-prune"),
    ("docker compose down -v", "docker.compose-down-volumes"),
    ('psql -c "DROP DATABASE production"', "database.destructive-sql"),
    ('mysql -e "DELETE FROM users WHERE id=1"', "database.destructive-sql"),
    ("kubectl delete namespace production", "kubernetes.delete-namespace"),
    ("terraform destroy", "terraform.destroy"),
    ("mkfs.ext4 /dev/sdb", "filesystem.format"),
    ("Remove-Item -Recurse -Force C:\\data", "powershell.remove-recursive"),
    ("rd /s /q C:\\data", "windows.recursive-delete"),
    ("wsl --unregister Ubuntu", "windows.wsl-unregister"),
])
def test_builtin_denies_destructive_commands(command, rule):
    result = BuiltinGuardProvider().inspect(GuardRequest("run_command", {}, command))
    assert result.decision == "deny"
    assert result.rule_id == rule
    assert result.remediation and result.remediation.commands


@pytest.mark.parametrize("command", [
    'echo "rm -rf /"',
    'printf "git reset --hard"',
    'python -c "print(\'git reset --hard\')"',
    'echo safe | grep "git reset --hard"',
    'cat file | grep "DROP DATABASE"',
    'grep "DROP DATABASE" documentation.md',
    "git clean -nd",
    "git push --force-with-lease",
    "Remove-Item -Recurse -WhatIf C:\\data",
])
def test_builtin_avoids_data_and_preview_false_positives(command):
    assert BuiltinGuardProvider().inspect(GuardRequest("run_command", {}, command)).decision == "allow"


def test_builtin_inspects_chains_substitutions_inline_shell_ssh_and_wsl():
    provider = BuiltinGuardProvider()
    commands = [
        "echo ok && git reset --hard",
        "echo $(rm -rf ./data)",
        "bash -c 'git stash clear'",
        "ssh host 'docker volume prune'",
        "wsl.exe bash -c 'terraform destroy'",
        "printf 'rm -rf /' | sh",
        "/bin/rm -rf ./data",
        "rm --recursive --force ./data",
        "git -C /tmp reset --hard",
        "git clean --force -d",
        "git push -f origin main",
        "env rm -rf ./data",
        "find . -type f | xargs rm -rf",
        "echo git reset --hard | xargs sh -c",
        "command rm -rf ./data",
        "sudo env rm -rf ./data",
        "busybox rm -rf ./data",
        "git clean -f -d",
        "python -c \"print('ok'); __import__('os').system('rm -rf ./data')\"",
        "cat payload | grep rm | sh",
        "cat sql | grep 'DROP TABLE' | psql",
    ]
    assert all(provider.inspect(GuardRequest("run_command", {}, value)).decision == "deny" for value in commands)


def test_root_and_home_resolution_uses_working_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    request = GuardRequest("run_command", {}, "rm -rf .", working_directory=str(tmp_path))
    assert BuiltinGuardProvider().inspect(request).rule_id == "filesystem.root-home-delete"


def test_force_push_remediation_is_safe_replacement():
    result = BuiltinGuardProvider().inspect(GuardRequest("run_command", {}, "git push --force"))
    assert result.remediation.commands == ("git push --force-with-lease",)


def test_service_falls_back_when_dcg_is_unavailable(monkeypatch):
    monkeypatch.setattr("command_guard.shutil.which", lambda _: None)
    events = []
    service = GuardService(provider="dcg", fallback="builtin", event_logger=lambda a, p: events.append((a, p)))
    result = service.inspect(GuardRequest("run_command", {}, "git reset --hard"))
    assert result.decision == "deny"
    assert result.guard == "builtin"
    assert events[0][0] == "command_guard_provider_failure"


def test_dcg_uses_machine_protocol_and_normalizes_result(monkeypatch):
    class Completed:
        returncode = 1
        stdout = json.dumps({
            "decision": "deny",
            "pack_id": "core.git",
            "rule_id": "reset-hard",
            "reason": "destroys changes",
            "suggestion": "stash first",
        })
        stderr = ""

    class Version:
        returncode = 0
        stdout = "dcg 0.6.7"
        stderr = ""

    calls = iter((Version(), Completed()))
    monkeypatch.setattr("command_guard.shutil.which", lambda _: "/usr/bin/dcg")
    monkeypatch.setattr("command_guard.subprocess.run", lambda *a, **k: next(calls))
    result = DcgGuardProvider().inspect(GuardRequest("run_command", {}, "git reset --hard", "/tmp"))
    assert result.decision == "deny"
    assert result.rule_id == "core.git:reset-hard"
    assert result.remediation.summary == "stash first"
    assert result.remediation.commands == ()


def test_redactor_recursively_removes_common_secret_forms(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "sentinel-secret-value")
    redactor = SecretRedactor.from_environ(os.environ)
    payload = {
        "command": "curl -H 'Authorization: Bearer abc123' https://user:pass@example.test --password hunter2 --password 'quoted-hunter2' --token \"quoted-abc123\" sentinel-secret-value",
        "nested": ["postgres://admin:secret@db/prod", "token=xyz987"],
    }
    rendered = repr(redactor.redact_value(payload))
    for secret in ("abc123", "user:pass", "hunter2", "quoted-hunter2", "quoted-abc123", "sentinel-secret-value", "admin:secret", "xyz987"):
        assert secret not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.parametrize("failure", ["crash", "timeout", "malformed"])
def test_dcg_failures_fall_back_to_builtin(monkeypatch, failure):
    class Version:
        returncode = 0
        stdout = "dcg 0.6.7"
        stderr = ""

    class Malformed:
        returncode = 0
        stdout = '{"decision":"allow","reason":["invalid"]}'
        stderr = ""

    calls = 0

    def run(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Version()
        if failure == "crash":
            raise OSError("dcg crashed")
        if failure == "timeout":
            import subprocess
            raise subprocess.TimeoutExpired(args[0], 1)
        return Malformed()

    monkeypatch.setattr("command_guard.shutil.which", lambda _: "/usr/bin/dcg")
    monkeypatch.setattr("command_guard.subprocess.run", run)
    result = GuardService(provider="dcg", fallback="builtin").inspect(
        GuardRequest("run_command", {}, "git reset --hard")
    )
    assert result.decision == "deny"
    assert result.guard == "builtin"


def test_dcg_runtime_rejects_unexpected_version_without_config(monkeypatch):
    class Version:
        returncode = 0
        stdout = "dcg 99.0.0"
        stderr = ""

    monkeypatch.setattr("command_guard.shutil.which", lambda _: "/usr/bin/dcg")
    monkeypatch.setattr("command_guard.subprocess.run", lambda *a, **k: Version())
    result = GuardService(provider="dcg", fallback="builtin").inspect(
        GuardRequest("run_command", {}, "git reset --hard")
    )
    assert result.guard == "builtin"
    assert result.decision == "deny"

def test_disabled_provider_allows_destructive_command():
    result = GuardService(provider="disabled", fallback="builtin").inspect(
        GuardRequest("run_command", {}, "rm -rf /")
    )
    assert result.decision == "allow"
    assert result.guard == "disabled"


def test_audit_contains_request_context():
    events = []
    service = GuardService(event_logger=lambda action, payload: events.append((action, payload)))
    service.inspect(GuardRequest("run_command", {}, "git reset --hard", "/tmp", "host-a", "Linux"))
    payload = events[-1][1]
    assert payload["tool"] == "run_command"
    assert payload["host"] == "host-a"
    assert payload["working_directory"] == "/tmp"
    assert payload["platform"] == "Linux"


def test_dcg_preserves_structured_remediation_commands(monkeypatch):
    class Version:
        returncode = 0
        stdout = "dcg 0.6.7"
        stderr = ""
    class Denied:
        returncode = 1
        stdout = json.dumps({"decision": "deny", "reason": "danger", "remediation": {"summary": "backup", "commands": ["git status", "git stash"]}})
        stderr = ""
    calls = iter((Version(), Denied()))
    monkeypatch.setattr("command_guard.shutil.which", lambda _: "/usr/bin/dcg")
    monkeypatch.setattr("command_guard.subprocess.run", lambda *a, **k: next(calls))
    result = DcgGuardProvider().inspect(GuardRequest("run_command", {}, "git reset --hard", "/tmp"))
    assert result.remediation.commands == ("git status", "git stash")


def custom_rule(**overrides):
    from command_guard_config import CustomGuardRule
    payload = {
        "id": "protect-model",
        "label": "Protect model",
        "enabled": True,
        "match_type": "contains",
        "pattern": "--model openai/",
        "reason": "Remote model use is blocked here.",
        "remediation": {"summary": "Use the local model.", "commands": ["opencode models"]},
    }
    payload.update(overrides)
    return CustomGuardRule.from_mapping(payload)


def test_builtin_catalog_exposes_18_logical_read_only_descriptions():
    rules = BuiltinGuardProvider().describe_rules()
    assert len(rules) == 18
    by_id = {rule["id"]: rule for rule in rules}
    assert len(by_id["filesystem.rm-recursive-force"]["patterns"]) == 2
    assert all({"id", "category", "patterns", "reason", "remediation_summary"} <= set(rule) for rule in rules)


def test_custom_contains_and_glob_rules_deny_case_insensitively():
    from command_guard import CustomGuardProvider
    contains = custom_rule(pattern="--MODEL OPENAI/")
    glob = custom_rule(id="protect-prod", match_type="glob", pattern="*deploy *production*")
    provider = CustomGuardProvider([contains, glob])
    first = provider.inspect(GuardRequest("run_command", {}, "opencode run --model openai/example"))
    second = provider.inspect(GuardRequest("run_command", {}, "tool deploy app production now"))
    assert first.rule_id == "custom.protect-model"
    assert second.rule_id == "custom.protect-prod"


def test_disabled_custom_rule_allows_and_multiple_rules_are_supported():
    from command_guard import CustomGuardProvider
    provider = CustomGuardProvider([
        custom_rule(enabled=False),
        custom_rule(id="protect-prod", pattern="deploy production"),
    ])
    assert provider.inspect(GuardRequest("run_command", {}, "opencode run --model openai/example")).decision == "allow"
    assert provider.inspect(GuardRequest("run_command", {}, "deploy production now")).rule_id == "custom.protect-prod"


def test_custom_rules_run_before_builtin_and_dcg(monkeypatch):
    custom = custom_rule(pattern="git branch")
    builtin_service = GuardService(provider="builtin", custom_rules=[custom])
    command = "git branch " + "-D old"
    result = builtin_service.inspect(GuardRequest("run_command", {}, command))
    assert result.guard == "custom"
    assert result.rule_id == "custom.protect-model"

    dcg_service = GuardService(provider="dcg", fallback="builtin", custom_rules=[custom])
    monkeypatch.setattr(dcg_service.providers["dcg"], "inspect", lambda request: (_ for _ in ()).throw(AssertionError("dcg should not run")))
    assert dcg_service.inspect(GuardRequest("run_command", {}, command)).guard == "custom"


def test_disabled_provider_bypasses_custom_rules():
    service = GuardService(provider="disabled", fallback="builtin", custom_rules=[custom_rule()])
    result = service.inspect(GuardRequest("run_command", {}, "opencode run --model openai/example"))
    assert result.decision == "allow"
    assert result.guard == "disabled"


def test_replace_custom_rules_updates_matching_immediately():
    service = GuardService(custom_rules=[custom_rule(pattern="first-marker")])
    assert service.inspect(GuardRequest("run_command", {}, "echo first-marker")).guard == "custom"
    service.replace_custom_rules([custom_rule(pattern="second-marker")])
    assert service.inspect(GuardRequest("run_command", {}, "echo first-marker")).decision == "allow"
    assert service.inspect(GuardRequest("run_command", {}, "echo second-marker")).guard == "custom"
