from pathlib import Path


RUN_PS1 = Path(__file__).resolve().parents[1] / "run.ps1"


def test_windows_launcher_supports_all_tunnel_providers():
    content = RUN_PS1.read_text()
    assert '@("ngrok", "tailscale", "external")' in content
    assert '@("funnel", "--bg=false", "$TunnelPort")' in content
    assert 'TUNNEL_PROVIDER=external requires MCP_BASE_URL=https://...' in content


def test_windows_tailscale_persists_detected_public_url_before_gateway():
    content = RUN_PS1.read_text()
    detect = content.index('tailscale funnel status --json')
    persist = content.index('Set-EnvValue "MCP_BASE_URL" $PublicUrl')
    gateway = content.index('$Gateway = Start-Process')
    assert detect < persist < gateway
    assert 'Set-EnvValue "OAUTH_ISSUER" "$PublicUrl/oauth"' in content
    assert 'Set-EnvValue "LOCAL_OAUTH_ISSUER" "$PublicUrl/oauth"' in content


def test_windows_reuses_existing_tailscale_funnel():
    content = RUN_PS1.read_text()
    status = content.index('$ExistingStatus = (& tailscale funnel status --json')
    reuse = content.index('Write-Host "Reusing active Tailscale Funnel."')
    start = content.index('$Tunnel = Start-Process -FilePath $TunnelCommand')
    assert status < reuse < start
    assert '$LASTEXITCODE -eq 0 -and $ExistingUrlMatch.Success' in content
