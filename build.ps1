# Builds dist\TrybunAI.exe. Optional: .\build.ps1 -CopyTo "K:\jakis\projekt"
param([string]$CopyTo)
# Failures are detected through $LASTEXITCODE: PyInstaller logs to stderr, and
# under 'Stop' Windows PowerShell would treat those log lines as fatal.
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    py -3.13 -m venv .venv
    & $python -m pip install --quiet --disable-pip-version-check -r requirements.txt
}

& $python -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw "Testy nie przeszly" }

& $python make_assets.py
if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie przygotowac logo" }

& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name TrybunAI `
    --icon "assets\icon.ico" --add-data "ui\index.html;ui" --add-data "ui\logo.png;ui" app.py
if ($LASTEXITCODE -ne 0) { throw "Budowanie nie powiodlo sie" }

if ($CopyTo) { Copy-Item dist\TrybunAI.exe -Destination $CopyTo -Force }
Write-Host "Gotowe: $(Resolve-Path dist\TrybunAI.exe)"
