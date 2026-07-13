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

$Gateway = Start-Process `
    -FilePath $Python `
    -ArgumentList "start_services.py" `
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
