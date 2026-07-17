from __future__ import annotations

from pathlib import Path

from .paths import GatePaths


def selected_logs(paths: GatePaths, *, gateway: bool, ngrok: bool) -> list[Path]:
    choices: list[Path] = []
    if gateway:
        choices.append(paths.logs / "services" / "gateway.log")
    if ngrok:
        choices.append(paths.logs / "ngrok.log")
    if not gateway and not ngrok:
        choices.extend([paths.logs / "services" / "gateway.log", paths.logs / "ngrok.log"])
    return [path for path in choices if path.exists()]
