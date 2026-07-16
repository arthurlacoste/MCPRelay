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
    realtime_enabled: bool
    widget_enabled: bool

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "RuntimeFeatures":
        realtime = env_flag(environ, "MCP_REALTIME_STATUS_ENABLED", True)
        widget = env_flag(environ, "MCP_WIDGET_ENABLED", False)
        if widget and not realtime:
            logging.info("ChatGPT widget enables realtime command status")
            realtime = True
        return cls(realtime_enabled=realtime, widget_enabled=widget)


def runtime_mode_summary(features: RuntimeFeatures) -> str:
    realtime = "on" if features.realtime_enabled else "off"
    widget = "on" if features.widget_enabled else "off"
    return f"realtime={realtime} widget={widget}"
