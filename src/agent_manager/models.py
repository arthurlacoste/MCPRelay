from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AGENT_STATUS_QUEUED = "queued"
AGENT_STATUS_RUNNING = "running"
AGENT_STATUS_COMPLETED = "completed"
AGENT_STATUS_FAILED = "failed"
AGENT_STATUS_CANCELLED = "cancelled"
AGENT_STATUS_STALE = "stale"
AGENT_STATUS_TIMEOUT_SOFT = "timeout_soft"
AGENT_STATUS_TIMEOUT_HARD = "timeout_hard"
AGENT_STATUS_NEEDS_REVIEW = "needs_review"

TERMINAL_AGENT_STATUSES = {
    AGENT_STATUS_COMPLETED,
    AGENT_STATUS_FAILED,
    AGENT_STATUS_CANCELLED,
    AGENT_STATUS_STALE,
    AGENT_STATUS_TIMEOUT_HARD,
    AGENT_STATUS_NEEDS_REVIEW,
}


@dataclass
class AgentSpec:
    prompt: str
    provider: str = "deepseek"
    purpose: str | None = None
    cwd: str | None = None
    model: str | None = None
    api_base: str | None = None
    auto_run: bool = False
    llm_supports_functions: bool = True
    context_window: int = 8192
    max_tokens: int = 4000
    wait_timeout_seconds: int = 10
    agent_timeout_seconds: int | None = None
    conversation_id: str | None = None
    chatgpt_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRecord:
    agent_id: str
    status: str
    prompt: str
    provider: str = "deepseek"
    purpose: str | None = None
    cwd: str | None = None
    model: str | None = None
    api_base: str | None = None
    auto_run: bool = False
    llm_supports_functions: bool = True
    context_window: int = 8192
    max_tokens: int = 4000
    wait_timeout_seconds: int = 10
    agent_timeout_seconds: int | None = None
    conversation_id: str | None = None
    chatgpt_url: str | None = None
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    heartbeat_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None


def redact_agent_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            sensitive = (
                lowered in {"token", "access_token", "refresh_token", "auth_token", "password", "secret"}
                or lowered.endswith("_token")
                or "api_key" in lowered
                or "secret" in lowered
                or "password" in lowered
            )
            if sensitive:
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact_agent_payload(value)
        return redacted
    if isinstance(payload, list):
        return [redact_agent_payload(item) for item in payload]
    return payload
