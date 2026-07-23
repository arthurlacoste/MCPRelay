from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping


TRUTHY = {"1", "true", "yes", "on"}


def env_flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


@dataclass(frozen=True)
class RuntimeFeatures:
    command_queue_enabled: bool
    widget_enabled: bool

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "RuntimeFeatures":
        if "MCP_COMMAND_QUEUE_ENABLED" in environ:
            command_queue = env_flag(environ, "MCP_COMMAND_QUEUE_ENABLED", True)
        else:
            command_queue = env_flag(environ, "MCP_REALTIME_STATUS_ENABLED", True)
        widget = env_flag(environ, "MCP_WIDGET_ENABLED", False)
        if widget and not command_queue:
            logging.info("ChatGPT widget enables the asynchronous command queue")
            command_queue = True
        return cls(command_queue_enabled=command_queue, widget_enabled=widget)


def runtime_mode_summary(features: RuntimeFeatures) -> str:
    command_queue = "on" if features.command_queue_enabled else "off"
    widget = "on" if features.widget_enabled else "off"
    return f"queue={command_queue} monitor=on widget={widget}"
