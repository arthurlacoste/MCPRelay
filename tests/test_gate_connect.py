from pathlib import Path

import os
import subprocess

import pytest

from gate_cli import connect


def _patch(monkeypatch, tmp_path: Path):
    env_file = tmp_path / "config" / ".env"
    monkeypatch.setattr(connect, "project_config_file", lambda: env_file)
    monkeypatch.setattr(connect, "cloudflared_executable", lambda: "/usr/bin/cloudflared")
    monkeypatch.setattr(connect, "cloudflared_logged_in", lambda: True)
    monkeypatch.setattr(connect, "tunnel_exists", lambda name: True)
    monkeypatch.setattr(connect, "route_dns", lambda name, hostname: True)
    monkeypatch.setattr(connect, "cloudflare_zone", lambda: "")
    return env_file


def test_connect_writes_named_tunnel_config(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)

    assert connect.command_connect("cf", tunnel_name="gate", hostname="mcp.example.com") == 0

    written = env_file.read_text()
    assert "TUNNEL_PROVIDER=cloudflare" in written
    assert "CLOUDFLARED_TUNNEL_NAME=gate" in written
    assert "MCP_BASE_URL=https://mcp.example.com" in written
    assert "OAUTH_ISSUER=https://mcp.example.com/oauth" in written
    assert "LOCAL_OAUTH_ISSUER=https://mcp.example.com/oauth" in written
    assert "gate setup" in capsys.readouterr().out


def test_connect_installs_cloudflared_when_missing(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    found = {"value": None}
    monkeypatch.setattr(connect, "cloudflared_executable", lambda: found["value"])
    installed = []
    monkeypatch.setattr(
        connect,
        "install_cloudflared",
        lambda: installed.append(True) or found.__setitem__("value", "/usr/bin/cloudflared") or True,
    )

    assert connect.command_connect("cloudflare", hostname="mcp.example.com", yes=True) == 0
    assert installed == [True]


def test_connect_logs_in_when_not_logged_in(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflared_logged_in", lambda: False)
    monkeypatch.setattr(connect, "cloudflared_login", lambda: True)

    assert connect.command_connect("cf", hostname="mcp.example.com") == 0
    assert "Logging in to Cloudflare" in capsys.readouterr().out


def test_connect_creates_tunnel_when_missing(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    created = []
    monkeypatch.setattr(connect, "tunnel_exists", lambda name: False)
    monkeypatch.setattr(connect, "create_tunnel", lambda name: created.append(name) or True)

    assert connect.command_connect("cf", hostname="mcp.example.com") == 0
    assert created == ["gate"]


def test_connect_rejects_unsupported_provider(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    assert connect.command_connect("ngrok") == 1
    assert "Unsupported provider" in capsys.readouterr().out


def test_connect_derives_hostname_from_existing_url(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("MCP_BASE_URL=https://mcp.example.com\n")

    assert connect.command_connect("cf", input_func=lambda _: "") == 0
    written = env_file.read_text()
    assert "CLOUDFLARED_TUNNEL_NAME=gate" in written
    assert "MCP_BASE_URL=https://mcp.example.com" in written


def test_connect_refuses_to_reuse_other_providers_url(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("MCP_BASE_URL=https://hull-envision-bunkbed.ngrok-free.dev\n")

    assert connect.command_connect("cf", input_func=lambda _: "mcp.example.com") == 0
    out = capsys.readouterr().out
    assert "belongs to another tunnel provider; it will not be reused" in out
    written = env_file.read_text()
    assert "MCP_BASE_URL=https://mcp.example.com" in written
    assert "ngrok-free.dev" not in written


def test_connect_warns_when_switching_tunnel_provider(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("TUNNEL_PROVIDER=ngrok\n")

    assert connect.command_connect("cf", hostname="mcp.example.com") == 0
    assert "Switching tunnel provider from ngrok to cloudflare" in capsys.readouterr().out


def test_connect_prompts_with_zone_default(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflare_zone", lambda: "irz.fr")

    assert connect.command_connect("cf", input_func=lambda _: "") == 0
    written = env_file.read_text()
    assert "MCP_BASE_URL=https://mcp.irz.fr" in written


def test_connect_appends_zone_to_single_label_input(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflare_zone", lambda: "irz.fr")

    assert connect.command_connect("cf", input_func=lambda _: "mcp") == 0
    written = env_file.read_text()
    assert "MCP_BASE_URL=https://mcp.irz.fr" in written


def test_connect_appends_zone_to_direct_hostname(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflare_zone", lambda: "irz.fr")

    # A single-label hostname passed directly (--hostname mcp) must not raise
    # UnboundLocalError on the zone lookup.
    assert connect.command_connect("cf", hostname="mcp") == 0

    written = env_file.read_text()
    assert "MCP_BASE_URL=https://mcp.irz.fr" in written


def test_route_dns_tolerates_existing_record(monkeypatch):
    monkeypatch.setattr(
        connect,
        "_run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="A record already exists for 'mcp.example.com'"
        ),
    )

    assert connect.route_dns("gate", "mcp.example.com") is True


def test_route_dns_fails_on_unrelated_errors(monkeypatch):
    monkeypatch.setattr(
        connect,
        "_run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="zone not found"),
    )

    assert connect.route_dns("gate", "mcp.example.com") is False


def test_cloudflare_zone_returns_empty_when_no_cert(monkeypatch, tmp_path):
    monkeypatch.setattr(connect.Path, "home", classmethod(lambda cls: tmp_path))
    assert connect.cloudflare_zone() == ""


def test_connect_requires_hostname_when_unconfigured(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    assert connect.command_connect("cf", input_func=lambda _: "  ") == 1
    assert "public hostname is required" in capsys.readouterr().out


def test_connect_aborts_when_install_declined(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflared_executable", lambda: None)
    monkeypatch.setattr(connect, "install_cloudflared", lambda: True)

    assert connect.command_connect("cf", hostname="mcp.example.com", input_func=lambda _: "n") == 1
    assert "Aborted" in capsys.readouterr().out


def test_connect_fails_cleanly_when_login_fails(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "cloudflared_logged_in", lambda: False)
    monkeypatch.setattr(connect, "cloudflared_login", lambda: False)

    assert connect.command_connect("cf", hostname="mcp.example.com") == 1
    assert "login failed" in capsys.readouterr().out


def test_connect_fails_cleanly_when_dns_route_fails(monkeypatch, tmp_path, capsys):
    _patch(monkeypatch, tmp_path)
    monkeypatch.setattr(connect, "route_dns", lambda name, hostname: False)

    assert connect.command_connect("cf", hostname="mcp.example.com") == 1
    assert "Could not route DNS" in capsys.readouterr().out


def test_tunnel_exists_matches_exact_name(monkeypatch):
    def run(command, **kwargs):
        stdout = '[{"name": "gate", "id": "1"}]' if "--name" in command else "[]"
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(connect, "_run", run)
    assert connect.tunnel_exists("gate") is True


def test_tunnel_exists_ignores_longer_names(monkeypatch):
    def run(command, **kwargs):
        if "--name" in command:
            return subprocess.CompletedProcess(command, 1, stdout="")
        return subprocess.CompletedProcess(command, 0, stdout='[{"name": "gate-prod"}]')

    monkeypatch.setattr(connect, "_run", run)
    assert connect.tunnel_exists("gate") is False


def test_connect_never_reuses_url_from_other_provider(monkeypatch, tmp_path, capsys):
    env_file = _patch(monkeypatch, tmp_path)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("TUNNEL_PROVIDER=external\nMCP_BASE_URL=https://mcp.example.com\n")
    routed = []
    monkeypatch.setattr(connect, "route_dns", lambda name, hostname: routed.append(hostname) or True)

    assert connect.command_connect("cf", input_func=lambda _: "api.example.com") == 0
    assert routed == ["api.example.com"]
    out = capsys.readouterr().out
    assert "Switching tunnel provider from external to cloudflare" in out
    assert "belongs to another tunnel provider; it will not be reused" in out
    written = env_file.read_text()
    assert "MCP_BASE_URL=https://api.example.com" in written


def test_install_cloudflared_linux_amd64(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["curl", "-fsSL"]:
            Path(command[4]).write_bytes(b"#!cloudflared\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(connect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(connect.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(connect, "_run", run)
    monkeypatch.setenv("GATE_ROOT", str(tmp_path))
    old_path = os.environ.get("PATH", "")
    try:
        assert connect.install_cloudflared() is True
        assert str(tmp_path / "runtime" / "bin") in os.environ["PATH"]
    finally:
        os.environ["PATH"] = old_path

    url = next(c for c in calls if c[:2] == ["curl", "-fsSL"])[2]
    assert url.endswith("cloudflared-linux-amd64")
    binary = tmp_path / "runtime" / "bin" / "cloudflared"
    assert binary.exists()
    assert binary.stat().st_mode & 0o111


def test_install_cloudflared_linux_arm64(monkeypatch, tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["curl", "-fsSL"]:
            Path(command[4]).write_bytes(b"#!cloudflared\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(connect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(connect.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(connect, "_run", run)
    monkeypatch.setenv("GATE_ROOT", str(tmp_path))
    old_path = os.environ.get("PATH", "")
    try:
        assert connect.install_cloudflared() is True
    finally:
        os.environ["PATH"] = old_path

    url = next(c for c in calls if c[:2] == ["curl", "-fsSL"])[2]
    assert url.endswith("cloudflared-linux-arm64")


def test_install_cloudflared_linux_unsupported_arch(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(connect.platform, "system", lambda: "Linux")
    monkeypatch.setattr(connect.platform, "machine", lambda: "mips64")
    monkeypatch.setenv("GATE_ROOT", str(tmp_path))
    assert connect.install_cloudflared() is False
    assert "Unsupported Linux architecture" in capsys.readouterr().out
