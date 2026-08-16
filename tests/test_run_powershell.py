from pathlib import Path


RUN_PS1 = Path(__file__).resolve().parents[1] / "run.ps1"


def test_windows_launcher_supports_all_tunnel_providers():
    content = RUN_PS1.read_text()
    assert '@("ngrok", "tailscale", "cloudflare", "external")' in content
    assert '@("funnel", "--bg=false", "$TunnelPort")' in content
    assert 'TUNNEL_PROVIDER=external requires MCP_BASE_URL=https://...' in content
    assert '@("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$TunnelPort")' in content


def test_windows_named_cloudflare_tunnel_uses_tunnel_name_and_url():
    content = RUN_PS1.read_text()
    assert '@("tunnel", "--no-autoupdate", "run", "--url", "http://127.0.0.1:$TunnelPort", $CloudflaredTunnelName)' in content
    assert 'CLOUDFLARED_TUNNEL_NAME requires MCP_BASE_URL=https://...' in content
    assert 'Get-EnvValue "CLOUDFLARED_TUNNEL_NAME"' in content


def test_windows_cloudflare_detects_url_before_gateway():
    content = RUN_PS1.read_text()
    cloudflare_start = content.index(
        'Start-Process -FilePath $TunnelCommand -ArgumentList $TunnelArgs '
        '-WorkingDirectory $ProjectDir -NoNewWindow -PassThru -RedirectStandardError $CloudflaredLog'
    )
    detect = content.index(r'https://[a-z0-9-]+\.trycloudflare\.com')
    persist = content.rfind('Set-EnvValue "MCP_BASE_URL" $PublicUrl')
    gateway = content.index('$Gateway = Start-Process')
    assert cloudflare_start < detect < persist < gateway
    assert 'Set-EnvValue "OAUTH_ISSUER" "$PublicUrl/oauth"' in content
    assert 'Set-EnvValue "LOCAL_OAUTH_ISSUER" "$PublicUrl/oauth"' in content


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
