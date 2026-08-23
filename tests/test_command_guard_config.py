import json
from pathlib import Path

import pytest

from command_guard_config import CustomGuardRule, CustomGuardStore, GuardConfigError, parse_config


def rule_payload(**overrides):
    payload = {
        "id": "protect-production-deploy",
        "label": "Protect production deploy",
        "enabled": True,
        "match_type": "contains",
        "pattern": "deploy production",
        "reason": "Production deployment requires manual review.",
        "remediation": {"summary": "Check target first.", "commands": ["git status --short"]},
    }
    payload.update(overrides)
    return payload


def test_rule_validation_and_round_trip():
    rule = CustomGuardRule.from_mapping(rule_payload())
    assert rule.id == "protect-production-deploy"
    assert rule.remediation_commands == ("git status --short",)
    assert CustomGuardRule.from_mapping(rule.as_dict()) == rule


@pytest.mark.parametrize("change", [
    {"id": "Bad ID"},
    {"match_type": "regex"},
    {"pattern": ""},
    {"enabled": "yes"},
    {"allow": True},
])
def test_invalid_rules_are_rejected(change):
    payload = rule_payload(**change)
    with pytest.raises(GuardConfigError):
        CustomGuardRule.from_mapping(payload)


def test_unknown_remediation_fields_are_rejected():
    payload = rule_payload(remediation={"summary": "safe", "commands": [], "allow": True})
    with pytest.raises(GuardConfigError):
        CustomGuardRule.from_mapping(payload)


def test_duplicate_ids_and_too_many_rules_are_rejected():
    duplicate = [rule_payload(), rule_payload()]
    with pytest.raises(GuardConfigError, match="duplicate"):
        parse_config({"version": 1, "rules": duplicate})
    many = [rule_payload(id=f"rule-{index}") for index in range(101)]
    with pytest.raises(GuardConfigError, match="at most 100"):
        parse_config({"version": 1, "rules": many})


def test_store_persists_atomically_and_reloads(tmp_path, monkeypatch):
    path = tmp_path / "config" / "command-guards.json"
    store = CustomGuardStore(path)
    rule = CustomGuardRule.from_mapping(rule_payload())
    replaces = []
    import command_guard_config
    original_replace = command_guard_config.os.replace

    def observed_replace(source, destination):
        source_path = Path(source)
        assert source_path.exists()
        json.loads(source_path.read_text(encoding="utf-8"))
        replaces.append((source_path, Path(destination)))
        return original_replace(source, destination)

    monkeypatch.setattr(command_guard_config.os, "replace", observed_replace)
    store.save([rule])

    assert replaces and replaces[0][1] == path
    assert store.load() == (rule,)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not list(path.parent.glob("*.tmp"))


def test_missing_store_is_empty_and_corrupt_store_fails_closed_to_caller(tmp_path):
    store = CustomGuardStore(tmp_path / "command-guards.json")
    assert store.load() == ()
    store.path.write_text("{broken", encoding="utf-8")
    with pytest.raises(GuardConfigError):
        store.load()


def test_direct_rule_instances_are_revalidated():
    invalid = CustomGuardRule(
        id="BAD ID", label="Bad", enabled=True, match_type="contains",
        pattern="marker", reason="reason",
    )
    store_rules = [invalid]
    from command_guard_config import validate_rules
    with pytest.raises(GuardConfigError):
        validate_rules(store_rules)


def test_boolean_config_version_is_rejected():
    with pytest.raises(GuardConfigError, match="version"):
        parse_config({"version": True, "rules": []})
