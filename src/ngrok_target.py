from __future__ import annotations

import ipaddress
import os
import subprocess
import sys
from collections.abc import Mapping


def resolve_ngrok_target(
    port: int,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> str:
    environ = os.environ if environ is None else environ
    override = environ.get("GATE_NGROK_TARGET", "").strip()
    if override:
        return override

    if (platform_name or sys.platform) != "darwin":
        return str(port)

    for interface in ("en0", "en1"):
        result = subprocess.run(
            ["ipconfig", "getifaddr", interface],
            capture_output=True,
            text=True,
            check=False,
        )
        address = result.stdout.strip()
        try:
            ipaddress.ip_address(address)
        except ValueError:
            continue
        return f"{address}:{port}"

    return str(port)
