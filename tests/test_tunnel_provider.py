import json
import subprocess
from pathlib import Path

import pytest

from src.tunnel_provider import (
    TunnelConfigurationError,
    build_tunnel_spec,
    normalize_provider,
    parse_tailscale_https_url,
    require_cli,
    tailscale_public_url,
    validate_tailscale_session,
)


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_provider_defaults_to_ngrok_and_accepts_supported_values():
    assert normalize_provider(None) == "ngrok"
    assert normalize_provider(" TAILSCALE ") == "tailscale"
    assert normalize_provider("external") == "external"


def test_unknown_provider_is_actionable():
    with pytest.raises(TunnelConfigurationError, match="Supported values"):
        normalize_provider("cloud-magic")


def test_missing_tailscale_cli_mentions_login_step():
    with pytest.raises(TunnelConfigurationError, match="tailscale up"):
        require_cli("tailscale", which=lambda _: None)


def test_tailscale_session_must_be_running():
    with pytest.raises(TunnelConfigurationError, match="not running"):
        validate_tailscale_session(
            run=lambda *args, **kwargs: completed(stdout=json.dumps({"BackendState": "Stopped"}))
        )


def test_tailscale_url_parser_extracts_public_https_url():
    output = 'Available on the internet:\nhttps://gate.example.ts.net/\n|-- proxy http://127.0.0.1:8761'
    assert parse_tailscale_https_url(output) == "https://gate.example.ts.net"


def test_process_arguments_for_each_provider(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("src.tunnel_provider.require_cli", lambda provider: f"/{provider}")
    monkeypatch.setattr("src.tunnel_provider.validate_tailscale_session", lambda: None)

    ngrok = build_tunnel_spec("ngrok", 8761, tmp_path)
    tailscale = build_tunnel_spec("tailscale", 8761, tmp_path)
    external = build_tunnel_spec("external", 8761, tmp_path)

    assert ngrok.command == ["ngrok", "http", "8761", "--log=stdout"]
    assert tailscale.command == ["tailscale", "funnel", "--bg=false", "8761"]
    assert external.command is None


def test_tailscale_public_url_reads_stdout_and_stderr():
    assert tailscale_public_url(
        run=lambda *args, **kwargs: completed(stdout="", stderr="https://gate.example.ts.net/\n")
    ) == "https://gate.example.ts.net"


def test_tailscale_public_url_rejects_missing_url():
    with pytest.raises(TunnelConfigurationError, match="Could not detect"):
        tailscale_public_url(run=lambda *args, **kwargs: completed(stdout="no funnel"))
