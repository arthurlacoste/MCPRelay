"""Gateway port selection shared by the launcher, supervisor, and gateway."""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Mapping


DEFAULT_GATEWAY_PORT = 8761
FALLBACK_ATTEMPTS = 10
MAX_TCP_PORT = 65535


class PortSelectionError(RuntimeError):
    """Raised when no usable gateway port can be selected."""


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def resolve_configured_port(environ: Mapping[str, str] | None = None) -> int:
    """Return the configured gateway port, validated against the TCP range."""
    raw = str(_environ(environ).get("GATEWAY_PORT", "")).strip()
    if not raw:
        return DEFAULT_GATEWAY_PORT
    try:
        port = int(raw)
    except ValueError:
        raise PortSelectionError(f"Invalid GATEWAY_PORT value: {raw!r}") from None
    if not 1 <= port <= 65535:
        raise PortSelectionError(f"GATEWAY_PORT must be between 1 and 65535, got {port}.")
    return port


def auto_fallback_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Whether GATEWAY_AUTO_PORT opts into picking the next free port."""
    return str(_environ(environ).get("GATEWAY_AUTO_PORT", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """Return True when a TCP listener could bind the given port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def looks_like_gate(port: int, timeout: float = 0.5) -> bool:
    """Probe /oauth/health to recognize an already-running Gate instance."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/oauth/health",
        headers={"User-Agent": "Gate"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("ok") is True
        and isinstance(payload.get("issuer"), str)
        and bool(payload.get("issuer"))
    )


def busy_port_message(port: int, gate_detected: bool) -> str:
    """Human-facing guidance for a busy gateway port."""
    if gate_detected:
        return (
            f"Gateway port {port} is used by another running copy of Gate.\n"
            "Two gateways must not share one data directory; stop it first\n"
            "(or set GATEWAY_PORT in config/.env to run them separately)."
        )
    return (
        f"Gateway port {port} is already in use by another process.\n"
        "Stop it, or set GATEWAY_PORT in config/.env to another port,\n"
        f"or set GATEWAY_AUTO_PORT=true to pick a free port near {port} automatically."
    )


def select_gateway_port(
    environ: Mapping[str, str] | None = None,
    allow_fallback: bool | None = None,
    probe=None,
) -> tuple[int, str | None]:
    """Return ``(port, notice)`` for a usable gateway port.

    ``notice`` explains an automatic fallback choice; ``None`` means the
    configured port was free. Raises :class:`PortSelectionError` when the port
    is busy and fallback is disabled or unsafe.
    """
    environ = _environ(environ)
    probe = looks_like_gate if probe is None else probe
    configured = resolve_configured_port(environ)

    if is_port_available(configured):
        return configured, None

    if allow_fallback is None:
        allow_fallback = auto_fallback_enabled(environ)

    if not allow_fallback:
        raise PortSelectionError(busy_port_message(configured, probe(configured)))

    if probe(configured):
        raise PortSelectionError(busy_port_message(configured, True))

    top = min(configured + FALLBACK_ATTEMPTS, MAX_TCP_PORT)
    for candidate in range(configured + 1, top + 1):
        if is_port_available(candidate):
            return candidate, (
                f"Gateway port {configured} is busy; using {candidate} instead "
                "(set GATEWAY_PORT in config/.env to make this permanent)."
            )

    if top <= configured:
        raise PortSelectionError(
            f"Gateway port {configured} is busy and no higher TCP port exists."
        )
    raise PortSelectionError(
        f"No free port found between {configured + 1} and {top}."
    )
