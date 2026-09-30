$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".packages\flask") -or -not (Test-Path -LiteralPath ".packages\yt_dlp_ejs")) {
    Write-Host "Installing local dependencies (first launch only)..." -ForegroundColor Cyan
    python -m pip install --target .packages -r requirements.txt --disable-pip-version-check -q
}

$port = $null
foreach ($candidate in 5000..5010) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $candidate)
    try {
        $listener.Start()
        $port = $candidate
        break
    } catch [System.Net.Sockets.SocketException] {
        continue
    } finally {
        $listener.Stop()
    }
}
if ($null -eq $port) {
    throw "No free port found between 5000 and 5010. Close an older downloader instance and try again."
}
$env:DROPLY_PORT = [string]$port
$siteUrl = "http://127.0.0.1:$port"

Write-Host ""
Write-Host "Droply is running at $siteUrl" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop it." -ForegroundColor DarkGray
if ($env:DROPLY_NO_BROWSER -ne "1") {
    Start-Process $siteUrl
}
python app.py
