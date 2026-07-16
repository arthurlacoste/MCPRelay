param(
    [switch]$Widget,
    [switch]$Realtime
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$Python = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python 3 was not found in PATH."
}

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    throw "ngrok was not found in PATH."
}

$ServiceArgs = @("start_services.py")
if ($Widget) { $ServiceArgs += "--widget" }
if ($Realtime) { $ServiceArgs += "--realtime" }

$Gateway = Start-Process `
    -FilePath $Python `
    -ArgumentList $ServiceArgs `
    -WorkingDirectory $ProjectDir `
    -NoNewWindow `
    -PassThru

try {
    Start-Sleep -Seconds 2
    Write-Host "MCPRelay ready on http://localhost:8761/mcp"
    Write-Host "Starting ngrok. Press Ctrl+C to stop."
    & ngrok http 8761
} finally {
    if (-not $Gateway.HasExited) {
        & taskkill /PID $Gateway.Id /T /F | Out-Null
    }
}
