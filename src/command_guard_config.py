from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

RULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MATCH_TYPES = {"contains", "glob"}
MAX_RULES = 100


class GuardConfigError(ValueError):
    pass


@dataclass(frozen=True)
class CustomGuardRule:
    id: str
    label: str
    enabled: bool
    match_type: str
    pattern: str
    reason: str
    remediation_summary: str = ""
    remediation_commands: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CustomGuardRule":
        if not isinstance(payload, Mapping):
            raise GuardConfigError("rule must be an object")
        allowed = {"id", "label", "enabled", "match_type", "pattern", "reason", "remediation"}
        unknown = set(payload) - allowed
        if unknown:
            raise GuardConfigError(f"unknown rule fields: {', '.join(sorted(unknown))}")

        rule_id = _required_string(payload, "id", 64)
        if not RULE_ID_RE.fullmatch(rule_id):
            raise GuardConfigError("id must match [a-z0-9][a-z0-9._-]{0,63}")
        label = _required_string(payload, "label", 100)
        match_type = _required_string(payload, "match_type", 16)
        if match_type not in MATCH_TYPES:
            raise GuardConfigError("match_type must be contains or glob")
        pattern = _required_string(payload, "pattern", 500)
        reason = _required_string(payload, "reason", 500)
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise GuardConfigError("enabled must be a boolean")

        remediation = payload.get("remediation", {})
        if remediation is None:
            remediation = {}
        if not isinstance(remediation, Mapping):
            raise GuardConfigError("remediation must be an object")
        remediation_unknown = set(remediation) - {"summary", "commands"}
        if remediation_unknown:
            raise GuardConfigError(f"unknown remediation fields: {', '.join(sorted(remediation_unknown))}")
        summary = remediation.get("summary", "")
        if not isinstance(summary, str) or len(summary) > 500:
            raise GuardConfigError("remediation summary must be at most 500 characters")
        commands = remediation.get("commands", [])
        if not isinstance(commands, list) or len(commands) > 10:
            raise GuardConfigError("remediation commands must be a list with at most 10 entries")
        normalized_commands: list[str] = []
        for command in commands:
            if not isinstance(command, str) or not command.strip() or len(command) > 500:
                raise GuardConfigError("each remediation command must be 1..500 characters")
            normalized_commands.append(command.strip())

        return cls(
            id=rule_id,
            label=label,
            enabled=enabled,
            match_type=match_type,
            pattern=pattern,
            reason=reason,
            remediation_summary=summary.strip(),
            remediation_commands=tuple(normalized_commands),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "enabled": self.enabled,
            "match_type": self.match_type,
            "pattern": self.pattern,
            "reason": self.reason,
            "remediation": {"summary": self.remediation_summary, "commands": list(self.remediation_commands)},
        }


def _required_string(payload: Mapping[str, Any], key: str, maximum: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise GuardConfigError(f"{key} must be a string")
    value = value.strip()
    if not value or len(value) > maximum:
        raise GuardConfigError(f"{key} must be 1..{maximum} characters")
    return value


def validate_rules(rules: Iterable[CustomGuardRule]) -> tuple[CustomGuardRule, ...]:
    snapshot = tuple(rules)
    if len(snapshot) > MAX_RULES:
        raise GuardConfigError(f"at most {MAX_RULES} custom guard rules are allowed")
    normalized: list[CustomGuardRule] = []
    ids: set[str] = set()
    for rule in snapshot:
        if not isinstance(rule, CustomGuardRule):
            raise GuardConfigError("invalid custom guard rule")
        validated = CustomGuardRule.from_mapping(rule.as_dict())
        if validated.id in ids:
            raise GuardConfigError(f"duplicate rule id: {validated.id}")
        ids.add(validated.id)
        normalized.append(validated)
    return tuple(normalized)


def parse_config(payload: Mapping[str, Any]) -> tuple[CustomGuardRule, ...]:
    if not isinstance(payload, Mapping):
        raise GuardConfigError("config must be an object")
    unknown = set(payload) - {"version", "rules"}
    if unknown:
        raise GuardConfigError(f"unknown config fields: {', '.join(sorted(unknown))}")
    version = payload.get("version")
    if type(version) is not int or version != 1:
        raise GuardConfigError("unsupported command guard config version")
    rules_payload = payload.get("rules")
    if not isinstance(rules_payload, list):
        raise GuardConfigError("rules must be a list")
    if len(rules_payload) > MAX_RULES:
        raise GuardConfigError(f"at most {MAX_RULES} custom guard rules are allowed")
    return validate_rules(CustomGuardRule.from_mapping(item) for item in rules_payload)


class CustomGuardStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> tuple[CustomGuardRule, ...]:
        with self._lock:
            if not self.path.exists():
                return ()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GuardConfigError(f"failed to read custom command guards: {type(exc).__name__}") from exc
            return parse_config(payload)

    def save(self, rules: Iterable[CustomGuardRule]) -> tuple[CustomGuardRule, ...]:
        snapshot = validate_rules(rules)
        payload = {"version": 1, "rules": [rule.as_dict() for rule in snapshot]}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, self.path)
                _fsync_directory(self.path.parent)
            except Exception:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
                raise
        return snapshot


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
