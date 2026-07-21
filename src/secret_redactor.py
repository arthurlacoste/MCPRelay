from __future__ import annotations

import re
from typing import Any, Mapping


class SecretRedactor:
    _patterns = (
        re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s'\"]+"),
        re.compile(r"(?i)((?:--password|--token|--secret|--api-key|--access-key)(?:=|\s+))(?:(['\"])[^'\"]*\2|[^\s'\"]+)"),
        re.compile(r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|access[_-]?key)\s*=\s*)[^\s;&]+"),
        re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@", re.IGNORECASE),
    )

    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        self.secrets = tuple(sorted({value for value in secrets if len(value) >= 8}, key=len, reverse=True))

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "SecretRedactor":
        names = re.compile(r"(?i)(secret|token|password|passwd|api_?key|access_?key|authorization)")
        return cls(tuple(value for key, value in environ.items() if names.search(key)))

    def redact_text(self, value: str) -> str:
        result = value
        for secret in self.secrets:
            result = result.replace(secret, "[REDACTED]")
        for pattern in self._patterns:
            result = pattern.sub(lambda match: match.group(1) + "[REDACTED]", result)
        return result

    def redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {key: self.redact_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(item) for item in value)
        return value
