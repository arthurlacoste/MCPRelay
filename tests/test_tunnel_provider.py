import json
import subprocess
from pathlib import Path

import pytest

from src.tunnel_provider import (
    TunnelConfigurationError,
    build_tunnel_spec,
    cloudflared_public_url,
    cloudflared_registered,
    normalize_provider,
    parse_cloudflared_url,
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
    assert normalize_provider(" cloudflare ") == "cloudflare"
    assert normalize_provider("external") == "external"


def test_unknown_provider_is_actionable():
    with pytest.raises(TunnelConfigurationError, match="Supported values"):
        normalize_provider("cloud-magic")


def test_require_cli_uses_runtime_shutil_lookup(monkeypatch):
    monkeypatch.setattr("src.tunnel_provider.shutil.which", lambda name: f"/usr/bin/{name}")
    assert require_cli("ngrok") == "/usr/bin/ngrok"


def test_require_cli_resolves_cloudflared_binary_for_cloudflare_provider(monkeypatch):
    monkeypatch.setattr("src.tunnel_provider.shutil.which", lambda name: f"/usr/bin/{name}")
    assert require_cli("cloudflare") == "/usr/bin/cloudflared"


def test_missing_tailscale_cli_mentions_login_step():
    with pytest.raises(TunnelConfigurationError, match="tailscale up"):
        require_cli("tailscale", which=lambda _: None)


def test_missing_cloudflared_cli_mentions_install():
    with pytest.raises(TunnelConfigurationError, match="brew install cloudflared"):
        require_cli("cloudflare", which=lambda _: None)


def test_tailscale_session_must_be_running():
    with pytest.raises(TunnelConfigurationError, match="not running"):
        validate_tailscale_session(
            run=lambda *args, **kwargs: completed(stdout=json.dumps({"BackendState": "Stopped"}))
        )


def test_tailscale_url_parser_extracts_public_https_url():
    output = 'Available on the internet:\nhttps://gate.example.ts.net/\n|-- proxy http://127.0.0.1:8761'
    assert parse_tailscale_https_url(output) == "https://gate.example.ts.net"


def test_cloudflared_url_parser_extracts_trycloudflare_url():
    output = (
        "INF |  Your quick Tunnel has been created! Visit it at "
        "(it may take some time to be reachable):  |\n"
        "INF |  https://lucky-cats-42.trycloudflare.com                           |"
    )
    assert parse_cloudflared_url(output) == "https://lucky-cats-42.trycloudflare.com"


def test_cloudflared_url_parser_returns_empty_without_match():
    assert parse_cloudflared_url("no tunnel url here") == ""
    assert parse_cloudflared_url("https://example.com/not-a-quick-tunnel") == ""


def test_cloudflared_public_url_reads_log(tmp_path):
    log = tmp_path / "cloudflared.log"
    log.write_text("INF | https://cool-tunnels-7.trycloudflare.com |\n", encoding="utf-8")
    assert cloudflared_public_url(log) == "https://cool-tunnels-7.trycloudflare.com"


def test_cloudflared_public_url_tolerates_missing_log(tmp_path):
    assert cloudflared_public_url(tmp_path / "missing.log") == ""


def test_cloudflared_registered_detects_named_tunnel_readiness(tmp_path):
    log = tmp_path / "cloudflared.log"
    log.write_text("INF Registered tunnel connection connIndex=0", encoding="utf-8")
    assert cloudflared_registered(log) is True


def test_cloudflared_registered_tolerates_missing_log(tmp_path):
    assert cloudflared_registered(tmp_path / "missing.log") is False


def test_process_arguments_for_each_provider(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("src.tunnel_provider.require_cli", lambda provider: f"/{provider}")
    monkeypatch.setattr("src.tunnel_provider.validate_tailscale_session", lambda: None)

    ngrok = build_tunnel_spec("ngrok", 8761, tmp_path)
    tailscale = build_tunnel_spec("tailscale", 8761, tmp_path)
    cloudflare = build_tunnel_spec("cloudflare", 8761, tmp_path)
    cloudflare_connect = build_tunnel_spec("cloudflare", 8761, tmp_path, cloudflared_tunnel_name="gate")
    external = build_tunnel_spec("external", 8761, tmp_path)

    assert ngrok.command == ["ngrok", "http", "8761", "--log=stdout"]
    assert tailscale.command == ["tailscale", "funnel", "--bg=false", "8761"]
    assert cloudflare.command == [
        "cloudflared", "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:8761",
    ]
    assert cloudflare.log_path == tmp_path / "cloudflared.log"
    assert cloudflare_connect.command == [
        "cloudflared", "tunnel", "--no-autoupdate", "run", "--url", "http://127.0.0.1:8761", "gate",
    ]
    assert cloudflare_connect.display_name == "Cloudflare Tunnel (gate)"
    assert external.command is None


def test_tailscale_public_url_reads_stdout_and_stderr():
    assert tailscale_public_url(
        run=lambda *args, **kwargs: completed(stdout="", stderr="https://gate.example.ts.net/\n")
    ) == "https://gate.example.ts.net"


def test_tailscale_public_url_rejects_missing_url():
    with pytest.raises(TunnelConfigurationError, match="Could not detect"):
        tailscale_public_url(run=lambda *args, **kwargs: completed(stdout="no funnel"))


def test_tailscale_status_timeout_is_actionable():
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 10))
    with pytest.raises(TunnelConfigurationError, match="timed out"):
        validate_tailscale_session(run=timed_out)
    with pytest.raises(TunnelConfigurationError, match="timed out"):
        tailscale_public_url(run=timed_out)
