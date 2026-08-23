import json
import socket
from unittest.mock import Mock

import pytest

from src import gateway_port
from src.gateway_port import (
    PortSelectionError,
    auto_fallback_enabled,
    resolve_configured_port,
    select_gateway_port,
)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def occupy_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", 0))
    sock.listen(1)
    return sock, sock.getsockname()[1]


def test_resolve_configured_port_defaults_to_8761():
    assert resolve_configured_port({}) == gateway_port.DEFAULT_GATEWAY_PORT


def test_resolve_configured_port_reads_override():
    assert resolve_configured_port({"GATEWAY_PORT": "9100"}) == 9100


def test_resolve_configured_port_rejects_bad_values():
    with pytest.raises(PortSelectionError):
        resolve_configured_port({"GATEWAY_PORT": "http"})
    with pytest.raises(PortSelectionError):
        resolve_configured_port({"GATEWAY_PORT": "70000"})


def test_auto_fallback_enabled_parses_common_flags():
    assert not auto_fallback_enabled({})
    for value in ("1", "true", "YES", "on"):
        assert auto_fallback_enabled({"GATEWAY_AUTO_PORT": value})


def test_select_gateway_port_returns_free_configured_port():
    port = free_port()
    assert select_gateway_port({"GATEWAY_PORT": str(port)}) == (port, None)


def test_select_gateway_port_refuses_busy_port_without_fallback():
    sock, port = occupy_port()
    try:
        with pytest.raises(PortSelectionError) as excinfo:
            select_gateway_port(
                {"GATEWAY_PORT": str(port)},
                allow_fallback=False,
                probe=lambda _port: False,
            )
    finally:
        sock.close()
    message = str(excinfo.value)
    assert f"Gateway port {port} is already in use" in message
    assert "GATEWAY_AUTO_PORT=true" in message


def test_select_gateway_port_falls_back_to_next_free_port():
    sock, port = occupy_port()
    try:
        selected, notice = select_gateway_port(
            {"GATEWAY_PORT": str(port), "GATEWAY_AUTO_PORT": "true"},
            probe=lambda _port: False,
        )
    finally:
        sock.close()
    assert selected == port + 1
    assert notice is not None and f"using {selected}" in notice


def test_select_gateway_port_never_falls_back_when_held_by_gate(monkeypatch):
    sock, port = occupy_port()
    monkeypatch.setattr(gateway_port, "looks_like_gate", lambda _port: True)
    try:
        with pytest.raises(PortSelectionError) as excinfo:
            select_gateway_port(
                {"GATEWAY_PORT": str(port), "GATEWAY_AUTO_PORT": "true"},
                probe=None,
            )
    finally:
        sock.close()
    message = str(excinfo.value)
    assert "another running copy of Gate" in message
    assert "GATEWAY_AUTO_PORT" not in message.split("\n")[0]


def test_select_gateway_port_reports_exhausted_range(monkeypatch):
    port = free_port()
    monkeypatch.setattr(gateway_port, "is_port_available", lambda _port: False)
    with pytest.raises(PortSelectionError) as excinfo:
        select_gateway_port(
            {"GATEWAY_PORT": str(port), "GATEWAY_AUTO_PORT": "true"},
            probe=lambda _port: False,
        )
    assert f"No free port found between {port + 1}" in str(excinfo.value)


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_looks_like_gate_recognizes_health_payload(monkeypatch):
    payload = {"ok": True, "issuer": "https://example.test/oauth", "audience": "x"}
    monkeypatch.setattr(
        gateway_port.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(json.dumps(payload).encode()),
    )
    assert gateway_port.looks_like_gate(8761) is True

    monkeypatch.setattr(
        gateway_port.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(json.dumps({"status": "ok"}).encode()),
    )
    assert gateway_port.looks_like_gate(8761) is False

    monkeypatch.setattr(
        gateway_port.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(OSError("refused")),
    )
    assert gateway_port.looks_like_gate(8761) is False
