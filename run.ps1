param(
    [switch]$Widget,
    [switch]$Realtime
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$SkillsRoot = if ($env:MCP_SKILLS_ROOT) {
    $env:MCP_SKILLS_ROOT
} else {
    Join-Path $HOME ".gate\skills"
}
New-Item -ItemType Directory -Path $SkillsRoot -Force | Out-Null

$Python = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python 3 was not found in PATH."
}

$ConfigRoot = if ($env:MCP_CONFIG_ROOT) { $env:MCP_CONFIG_ROOT } else { Join-Path $ProjectDir "config" }
$GateRoot = if ($env:GATE_ROOT) { $env:GATE_ROOT } else { Join-Path $HOME ".gate" }
$GuardBin = Join-Path $GateRoot "runtime\bin"
$ConfigFile = Join-Path $ConfigRoot ".env"
$ConfiguredProvider = if (Test-Path $ConfigFile) {
    $Match = Select-String -Path $ConfigFile -Pattern '^MCP_COMMAND_GUARD_PROVIDER=(.+)$' | Select-Object -Last 1
    if ($Match) { $Match.Matches[0].Groups[1].Value } else { $null }
} else { $null }
if ($env:MCP_COMMAND_GUARD_PROVIDER -eq "disabled") {
    Write-Warning "Command guard disabled for this launch."
} elseif (-not $ConfiguredProvider) {
    $Provider = $env:GATE_COMMAND_GUARD_PROVIDER
    if (-not $Provider) {
        Write-Host "`nCommand safety guard"
        Write-Host "1. Built-in guard (default)"
        Write-Host "2. Destructive Command Guard (dcg)"
        $Choice = Read-Host "Choose [1/2]"
        $Provider = if ($Choice -eq "2") { "dcg" } else { "builtin" }
    }
    & $Python (Join-Path $ProjectDir "src\dcg_installer.py") --config-root $ConfigRoot --bin-dir $GuardBin --provider $Provider
}
$env:PATH = "$GuardBin$([IO.Path]::PathSeparator)$env:PATH"

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
    Write-Host "Gate ready on http://localhost:8761/mcp"
    Write-Host "Starting ngrok. Press Ctrl+C to stop."
    & ngrok http 8761
} finally {
    if (-not $Gateway.HasExited) {
        & taskkill /PID $Gateway.Id /T /F | Out-Null
    }
}
