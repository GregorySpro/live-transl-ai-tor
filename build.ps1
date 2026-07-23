# build.ps1 — Construit le bootstrap léger puis l'installeur
# Usage : .\build.ps1 [-SkipInstaller]
param([switch]$SkipInstaller)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

Write-Host "=== 1/2  PyInstaller (bootstrap léger) ===" -ForegroundColor Cyan
uv run pyinstaller "bootstrap.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller a échoué (code $LASTEXITCODE)"; exit 1 }

Write-Host ""
Write-Host "✅ Bootstrap : dist\live-transl-ai-tor-bootstrap\" -ForegroundColor Green

if ($SkipInstaller) { exit 0 }

Write-Host ""
Write-Host "=== 2/2  Inno Setup ===" -ForegroundColor Cyan

$iscc = Get-Command "ISCC" -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $iscc) {
    Write-Warning "Inno Setup introuvable — installer depuis https://jrsoftware.org/isinfo.php"
    Write-Host "Le bootstrap standalone est dispo dans dist\live-transl-ai-tor-bootstrap\" -ForegroundColor Yellow
    exit 0
}

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) { Write-Error "Inno Setup a échoué (code $LASTEXITCODE)"; exit 1 }

Write-Host ""
$size = [math]::Round((Get-Item "dist\live-transl-ai-tor-setup.exe").Length / 1MB, 1)
Write-Host "✅ Installeur : dist\live-transl-ai-tor-setup.exe ($size Mo)" -ForegroundColor Green
