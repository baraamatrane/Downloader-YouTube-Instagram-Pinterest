$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath ".packages\flask") -or -not (Test-Path -LiteralPath ".packages\yt_dlp_ejs")) {
    Write-Host "Installing local dependencies (first launch only)..." -ForegroundColor Cyan
    python -m pip install --target .packages -r requirements.txt --disable-pip-version-check -q
}

Write-Host ""
Write-Host "Droply is running at http://127.0.0.1:5000" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop it." -ForegroundColor DarkGray
Start-Process "http://127.0.0.1:5000"
python app.py
