param(
    [switch]$Widget,
    [switch]$Queue,
    [switch]$Realtime,
    [switch]$ConnectTs
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir
$ConfigRoot = if ($env:MCP_CONFIG_ROOT) { $env:MCP_CONFIG_ROOT } else { Join-Path $ProjectDir "config" }
$ConfigFile = Join-Path $ConfigRoot ".env"
$GateRoot = if ($env:GATE_ROOT) { $env:GATE_ROOT } else { Join-Path $HOME ".gate" }
$GuardBin = Join-Path $GateRoot "runtime\bin"
$TunnelPort = 8761

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path $ConfigFile)) { return $null }
    $Match = Select-String -Path $ConfigFile -Pattern "^$([regex]::Escape($Name))=(.*)$" | Select-Object -Last 1
    if ($Match) { return $Match.Matches[0].Groups[1].Value }
    return $null
}

$ConfiguredPort = if ($env:GATEWAY_PORT) { $env:GATEWAY_PORT } else { Get-EnvValue "GATEWAY_PORT" }
if ($ConfiguredPort -match '^\d+$' -and [int]$ConfiguredPort -ge 1 -and [int]$ConfiguredPort -le 65535) {
    $TunnelPort = [int]$ConfiguredPort
}

function Set-EnvValue([string]$Name, [string]$Value) {
    New-Item -ItemType Directory -Path $ConfigRoot -Force | Out-Null
    $Lines = if (Test-Path $ConfigFile) { Get-Content $ConfigFile } else { @() }
    $Lines = @($Lines | Where-Object { $_ -notmatch "^\s*$([regex]::Escape($Name))=" })
    $Lines += "$Name=$Value"
    Set-Content -Path $ConfigFile -Value $Lines -Encoding utf8
}

$SkillsRoot = if ($env:MCP_SKILLS_ROOT) { $env:MCP_SKILLS_ROOT } else { Join-Path $HOME ".gate\skills" }
New-Item -ItemType Directory -Path $SkillsRoot -Force | Out-Null

$Python = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python 3 was not found in PATH."
}

if ($ConnectTs) {
    $SrcDir = Join-Path $ProjectDir "src"
    if ($env:PYTHONPATH) { $env:PYTHONPATH = "$SrcDir;$env:PYTHONPATH" } else { $env:PYTHONPATH = $SrcDir }
    if (-not $env:GATE_PROJECT_DIR) { $env:GATE_PROJECT_DIR = $ProjectDir }
    & $Python -m gate_cli connect ts
    exit $LASTEXITCODE
}

$ConfiguredGuard = Get-EnvValue "MCP_COMMAND_GUARD_PROVIDER"
if ($env:MCP_COMMAND_GUARD_PROVIDER -eq "disabled") {
    Write-Warning "Command guard disabled for this launch."
} elseif (-not $ConfiguredGuard) {
    $GuardProvider = $env:GATE_COMMAND_GUARD_PROVIDER
    if (-not $GuardProvider) {
        Write-Host "`nCommand safety guard"
        Write-Host "1. Built-in guard (default)"
        Write-Host "2. Destructive Command Guard (dcg)"
        $Choice = Read-Host "Choose [1/2]"
        $GuardProvider = if ($Choice -eq "2") { "dcg" } else { "builtin" }
    }
    & $Python (Join-Path $ProjectDir "src\dcg_installer.py") --config-root $ConfigRoot --bin-dir $GuardBin --provider $GuardProvider
}
$env:PATH = "$GuardBin$([IO.Path]::PathSeparator)$env:PATH"

$TunnelProvider = if ($env:TUNNEL_PROVIDER) { $env:TUNNEL_PROVIDER } else { Get-EnvValue "TUNNEL_PROVIDER" }
if (-not $TunnelProvider) { $TunnelProvider = "ngrok" }
$TunnelProvider = $TunnelProvider.ToLowerInvariant()
if ($TunnelProvider -notin @("ngrok", "tailscale", "cloudflare", "external")) {
    throw "Unsupported TUNNEL_PROVIDER=$TunnelProvider. Use ngrok, tailscale, cloudflare, or external."
}
$CloudflaredTunnelName = if ($env:CLOUDFLARED_TUNNEL_NAME) { $env:CLOUDFLARED_TUNNEL_NAME } else { Get-EnvValue "CLOUDFLARED_TUNNEL_NAME" }

$TunnelCommand = $null
$TunnelArgs = @()
switch ($TunnelProvider) {
    "ngrok" {
        if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
            throw "ngrok was not found. Install ngrok and configure its authtoken."
        }
        $TunnelCommand = "ngrok"
        $TunnelArgs = @("http", "$TunnelPort")
    }
    "tailscale" {
        if (-not (Get-Command tailscale -ErrorAction SilentlyContinue)) {
            throw "Tailscale CLI was not found. Install Tailscale, run 'tailscale up', then retry."
        }
        $Status = & tailscale status --json 2>$null | ConvertFrom-Json
        if ($Status.BackendState -ne "Running") {
            throw "Tailscale is not authenticated or running. Run 'tailscale up' and retry."
        }
        $TunnelCommand = "tailscale"
        $TunnelArgs = @("funnel", "--bg=false", "$TunnelPort")
    }
    "cloudflare" {
        if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
            throw "cloudflared was not found. Install it (winget install --id Cloudflare.cloudflared), then retry."
        }
        if ($CloudflaredTunnelName) {
            $TunnelList = & cloudflared tunnel list 2>&1 | Out-String
            if ($LASTEXITCODE -ne 0) {
                throw "cloudflared is not logged in to Cloudflare. Run 'cloudflared tunnel login', then retry."
            }
            if ($TunnelList -notmatch [regex]::Escape($CloudflaredTunnelName)) {
                throw "Cloudflare tunnel '$CloudflaredTunnelName' does not exist. Run 'cloudflared tunnel create $CloudflaredTunnelName' or '.\run.ps1 setup'."
            }
        }
        $TunnelCommand = "cloudflared"
        if ($CloudflaredTunnelName) {
            $TunnelArgs = @("tunnel", "--no-autoupdate", "run", "--url", "http://127.0.0.1:$TunnelPort", $CloudflaredTunnelName)
        } else {
            $TunnelArgs = @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$TunnelPort")
        }
    }
    "external" {
        $PublicUrl = if ($env:MCP_BASE_URL) { $env:MCP_BASE_URL } else { Get-EnvValue "MCP_BASE_URL" }
        if (-not $PublicUrl -or -not $PublicUrl.StartsWith("https://")) {
            throw "TUNNEL_PROVIDER=external requires MCP_BASE_URL=https://..."
        }
    }
}
Set-EnvValue "TUNNEL_PROVIDER" $TunnelProvider

$ServiceArgs = @("start_services.py")
if ($Widget) { $ServiceArgs += "--widget" }
if ($Queue -or $Realtime) { $ServiceArgs += "--queue" }
$NgrokTarget = if ($env:GATE_NGROK_TARGET) { $env:GATE_NGROK_TARGET } else { "$TunnelPort" }
$Gateway = $null
$Tunnel = $null

try {
    if ($TunnelProvider -eq "tailscale") {
        $PublicUrl = $null
        $ExistingStatus = (& tailscale funnel status --json 2>&1 | Out-String)
        $ExistingUrlMatch = [regex]::Match($ExistingStatus, 'https://[^\s"'']+')
        if ($LASTEXITCODE -eq 0 -and $ExistingUrlMatch.Success) {
            $PublicUrl = $ExistingUrlMatch.Value.TrimEnd('/', '.', ',', ';', ')')
            Write-Host "Reusing active Tailscale Funnel."
        } else {
            Write-Host "Starting Tailscale Funnel."
            $Tunnel = Start-Process -FilePath $TunnelCommand -ArgumentList $TunnelArgs -WorkingDirectory $ProjectDir -NoNewWindow -PassThru
            for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
                if ($Tunnel.HasExited) { break }
                Start-Sleep -Seconds 1
                $FunnelStatus = (& tailscale funnel status --json 2>&1 | Out-String)
                $UrlMatch = [regex]::Match($FunnelStatus, 'https://[^\s"'']+')
                if ($UrlMatch.Success) {
                    $PublicUrl = $UrlMatch.Value.TrimEnd('/', '.', ',', ';', ')')
                    break
                }
            }
        }
        if (-not $PublicUrl) {
            throw "Could not detect a public Tailscale Funnel HTTPS URL. Confirm Funnel is enabled for this tailnet."
        }
        Set-EnvValue "MCP_BASE_URL" $PublicUrl
        Set-EnvValue "OAUTH_ISSUER" "$PublicUrl/oauth"
        Set-EnvValue "LOCAL_OAUTH_ISSUER" "$PublicUrl/oauth"
        Write-Host "Public URL: $PublicUrl"
    }

    if ($TunnelProvider -eq "cloudflare") {
        if ($CloudflaredTunnelName) {
            $PublicUrl = if ($env:MCP_BASE_URL) { $env:MCP_BASE_URL } else { Get-EnvValue "MCP_BASE_URL" }
            if (-not $PublicUrl -or -not $PublicUrl.StartsWith("https://")) {
                throw "CLOUDFLARED_TUNNEL_NAME requires MCP_BASE_URL=https://... (your tunnel hostname)."
            }
            Write-Host "Starting Cloudflare connect tunnel '$CloudflaredTunnelName'."
            $Tunnel = Start-Process -FilePath $TunnelCommand -ArgumentList $TunnelArgs -WorkingDirectory $ProjectDir -NoNewWindow -PassThru
        } else {
            $CloudflaredLog = Join-Path $ProjectDir "logs\cloudflared.log"
            New-Item -ItemType Directory -Path (Split-Path $CloudflaredLog) -Force | Out-Null
            Write-Host "Starting Cloudflare Tunnel."
            $Tunnel = Start-Process -FilePath $TunnelCommand -ArgumentList $TunnelArgs -WorkingDirectory $ProjectDir -NoNewWindow -PassThru -RedirectStandardError $CloudflaredLog
            $PublicUrl = $null
            for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
                if ($Tunnel.HasExited) { break }
                Start-Sleep -Seconds 1
                $LogText = Get-Content $CloudflaredLog -Raw -ErrorAction SilentlyContinue
                $UrlMatch = [regex]::Match($LogText, 'https://[a-z0-9-]+\.trycloudflare\.com')
                if ($UrlMatch.Success) {
                    $PublicUrl = $UrlMatch.Value.TrimEnd('/')
                    break
                }
            }
            if (-not $PublicUrl) {
                throw "Could not detect a public Cloudflare Tunnel HTTPS URL. Check $CloudflaredLog."
            }
            Set-EnvValue "MCP_BASE_URL" $PublicUrl
            Set-EnvValue "OAUTH_ISSUER" "$PublicUrl/oauth"
            Set-EnvValue "LOCAL_OAUTH_ISSUER" "$PublicUrl/oauth"
            Write-Host "Public URL: $PublicUrl"
        }
    }

    $Gateway = Start-Process -FilePath $Python -ArgumentList $ServiceArgs -WorkingDirectory $ProjectDir -NoNewWindow -PassThru
    Start-Sleep -Seconds 2
    Write-Host "Gate ready on http://localhost:$TunnelPort/mcp"

    if ($TunnelProvider -eq "ngrok") {
        Write-Host "Starting ngrok. Press Ctrl+C to stop."
        & $TunnelCommand "http" $NgrokTarget
        if ($LASTEXITCODE -ne 0) { throw "ngrok exited with code $LASTEXITCODE." }
    } elseif ($TunnelProvider -eq "tailscale") {
        Write-Host "Tailscale Funnel ready. Press Ctrl+C to stop."
        Wait-Process -Id $Tunnel.Id
    } else {
        Write-Host "External tunnel managed by user. Press Ctrl+C to stop Gate."
        Wait-Process -Id $Gateway.Id
    }
} finally {
    if ($Tunnel -and -not $Tunnel.HasExited) { & taskkill /PID $Tunnel.Id /T /F | Out-Null }
    if ($Gateway -and -not $Gateway.HasExited) { & taskkill /PID $Gateway.Id /T /F | Out-Null }
}
