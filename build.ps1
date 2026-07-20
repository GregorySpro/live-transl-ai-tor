# build.ps1 — Construit l'exe puis l'installeur
# Usage : .\build.ps1 [-SkipInstaller]
param([switch]$SkipInstaller)

Set-Location $PSScriptRoot
$ErrorActionPreference = "Stop"

Write-Host "=== 1/2  PyInstaller ===" -ForegroundColor Cyan
uv run pyinstaller "live-transl-ai-tor.spec" --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller a échoué (code $LASTEXITCODE)"; exit 1 }

Write-Host ""
Write-Host "✅ Exe généré : dist\live-transl-ai-tor\live-transl-ai-tor.exe" -ForegroundColor Green

if ($SkipInstaller) { exit 0 }

Write-Host ""
Write-Host "=== 2/2  Inno Setup ===" -ForegroundColor Cyan

$iscc = Get-Command "ISCC" -ErrorAction SilentlyContinue
if (-not $iscc) {
    # Chercher dans les emplacements habituels
    $candidates = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $iscc) {
    Write-Warning "Inno Setup introuvable — installez-le depuis https://jrsoftware.org/isinfo.php"
    Write-Warning "Ensuite relancez : .\build.ps1"
    Write-Host ""
    Write-Host "L'exe standalone est dispo dans dist\live-transl-ai-tor\" -ForegroundColor Yellow
    exit 0
}

& $iscc "installer.iss"
if ($LASTEXITCODE -ne 0) { Write-Error "Inno Setup a échoué (code $LASTEXITCODE)"; exit 1 }

Write-Host ""
Write-Host "✅ Installeur généré : dist\live-transl-ai-tor-setup.exe" -ForegroundColor Green
