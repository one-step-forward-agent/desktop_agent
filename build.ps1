# Builds dist\Deyla.exe: one file, no console window, the site-like window (Edge WebView2) with its page and icon.
# Run from desktop_agent\ in PowerShell.
[CmdletBinding()]
param([switch]$SkipInstall)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = if (Test-Path -LiteralPath '.venv\Scripts\python.exe') { '.venv\Scripts\python.exe' } else { 'python' }
if (-not $SkipInstall) {
  & $pythonExe -m pip install -r requirements-dev.txt
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
}
& $pythonExe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; executable was not rebuilt' }
& $pythonExe -m PyInstaller --noconfirm --clean --onefile --windowed --name Deyla --icon assets\deyla.ico `
  --collect-submodules pywinauto --collect-submodules comtypes.gen `
  --add-data "deyla_desktop\web;deyla_desktop\web" --add-data "assets\deyla.ico;assets" run.py
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
Write-Host "Built: $(Resolve-Path dist\Deyla.exe)"
