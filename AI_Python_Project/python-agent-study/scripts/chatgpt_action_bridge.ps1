[CmdletBinding()]
param(
    [ValidateSet("Start", "Stop", "Restart", "Status", "CopyKey")]
    [string]$Action = "Start",
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot ".tmp\chatgpt-action-bridge"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$bridge = Join-Path $PSScriptRoot "chatgpt_code_bridge.py"
$cloudflared = Join-Path $runtimeDir "cloudflared.exe"
$keyFile = Join-Path $runtimeDir "api-key.dpapi"
$apiPidFile = Join-Path $runtimeDir "api.pid"
$apiLauncherPidFile = Join-Path $runtimeDir "api-launcher.pid"
$tunnelPidFile = Join-Path $runtimeDir "tunnel.pid"
$tunnelLog = Join-Path $runtimeDir "tunnel.log"

function Stop-RecordedProcess {
    param([string]$PidFile, [string[]]$AllowedNames)

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }
    $processId = [int](Get-Content -Raw -LiteralPath $PidFile)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in $AllowedNames) {
        Stop-Process -Id $processId -Force
    }
    Remove-Item -LiteralPath $PidFile -Force
}

function Read-ApiKey {
    $secureKey = ConvertTo-SecureString ((Get-Content -Raw -LiteralPath $keyFile).Trim())
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Show-AndCopyApiKey {
    param([string]$ApiKey)

    Set-Clipboard -Value $ApiKey
    Write-Host ("API key: {0}" -f $ApiKey)
    Write-Host "API key copied to clipboard."
}

function Stop-Bridge {
    Stop-RecordedProcess $tunnelPidFile @("cloudflared")
    Stop-RecordedProcess $apiPidFile @("python", "pythonw")
    Stop-RecordedProcess $apiLauncherPidFile @("python", "pythonw")
    Write-Host "ChatGPT code bridge stopped."
}

function Get-BridgeStatus {
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 2
        Write-Host ("Local API: {0} ({1})" -f $health.status, $health.root)
    }
    catch {
        Write-Host "Local API: stopped"
    }

    if (Test-Path -LiteralPath $tunnelLog) {
        $match = Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
            Select-Object -Last 1
        if ($match) {
            Write-Host ("Tunnel: {0}" -f $match.Matches[0].Value)
        }
    }
}

if ($Action -eq "Stop") {
    Stop-Bridge
    exit 0
}
if ($Action -eq "Restart") {
    Stop-Bridge
}
if ($Action -eq "Status") {
    Get-BridgeStatus
    exit 0
}
if ($Action -eq "CopyKey") {
    if (-not (Test-Path -LiteralPath $keyFile)) {
        throw "No saved API key. Run this script with -Action Start first."
    }
    Show-AndCopyApiKey (Read-ApiKey)
    exit 0
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python not found: $python"
}
if (-not (Test-Path -LiteralPath $cloudflared)) {
    throw "cloudflared not found: $cloudflared"
}

try {
    $runningBridge = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 1
}
catch {
    $runningBridge = $null
}
if ($runningBridge) {
    if (-not (Test-Path -LiteralPath $keyFile)) {
        throw "The bridge is running, but its saved API key is missing."
    }
    Write-Host "ChatGPT code bridge is already running; reusing it."
    Show-AndCopyApiKey (Read-ApiKey)
    Get-BridgeStatus
    exit 0
}

$createdKey = -not (Test-Path -LiteralPath $keyFile)
if ($createdKey) {
    $bytes = New-Object byte[] 32
    $rng = New-Object Security.Cryptography.RNGCryptoServiceProvider
    $rng.GetBytes($bytes)
    $rng.Dispose()
    $apiKey = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    $secureKey = ConvertTo-SecureString $apiKey -AsPlainText -Force
    ConvertFrom-SecureString $secureKey | Set-Content -Encoding ASCII -LiteralPath $keyFile
}
else {
    $apiKey = Read-ApiKey
}

# Codex can provide duplicate Path/PATH entries; Windows PowerShell Start-Process rejects them.
$pathKeys = @([Environment]::GetEnvironmentVariables().Keys | Where-Object {
    $_.ToString().ToLowerInvariant() -eq "path"
})
if ($pathKeys.Count -gt 1) {
    Remove-Item Env:PATH -ErrorAction SilentlyContinue
}

$env:CHATGPT_BRIDGE_API_KEY = $apiKey
$apiProcess = Start-Process -FilePath $python `
    -ArgumentList @($bridge, "--root", $projectRoot, "--transport", "action", "--host", "127.0.0.1", "--port", $Port) `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $runtimeDir "api.stdout.log") `
    -RedirectStandardError (Join-Path $runtimeDir "api.stderr.log") `
    -PassThru
$apiProcess.Id | Set-Content -Encoding ASCII -LiteralPath $apiLauncherPidFile

$deadline = (Get-Date).AddSeconds(15)
do {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 1
    }
    catch {
        $health = $null
    }
} until ($health -or (Get-Date) -gt $deadline)
if (-not $health) {
    Stop-RecordedProcess $apiLauncherPidFile @("python", "pythonw")
    throw "Local API failed to start. See $runtimeDir\api.stderr.log"
}

$listener = netstat.exe -ano -p tcp | Select-String ("127.0.0.1:{0}\s+.*LISTENING" -f $Port) |
    Select-Object -First 1
if ($listener) {
    (($listener.ToString().Trim() -split '\s+')[-1]) | Set-Content -Encoding ASCII -LiteralPath $apiPidFile
}

$match = $null
for ($attempt = 1; $attempt -le 3 -and -not $match; $attempt++) {
    Remove-Item -LiteralPath $tunnelLog -Force -ErrorAction SilentlyContinue
    $tunnelProcess = Start-Process -FilePath $cloudflared `
        -ArgumentList @("tunnel", "--url", ("http://127.0.0.1:{0}" -f $Port), "--no-autoupdate", "--logfile", $tunnelLog, "--loglevel", "info") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtimeDir "tunnel.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDir "tunnel.stderr.log") `
        -PassThru
    $tunnelProcess.Id | Set-Content -Encoding ASCII -LiteralPath $tunnelPidFile

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        $match = if (Test-Path -LiteralPath $tunnelLog) {
            Select-String -Path $tunnelLog -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
                Select-Object -Last 1
        }
    } until ($match -or $tunnelProcess.HasExited -or (Get-Date) -gt $deadline)

    if (-not $match) {
        if (-not $tunnelProcess.HasExited) {
            Stop-Process -Id $tunnelProcess.Id -Force
        }
        Remove-Item -LiteralPath $tunnelPidFile -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}
if (-not $match) {
    Stop-Bridge
    throw "Tunnel failed to start. See $runtimeDir\tunnel.log"
}

$publicUrl = $match.Matches[0].Value
Show-AndCopyApiKey $apiKey
Write-Host ("Local API: http://127.0.0.1:{0}" -f $Port)
Write-Host ("Schema: {0}/openapi.json" -f $publicUrl)
Write-Host ("Privacy: {0}/privacy" -f $publicUrl)
