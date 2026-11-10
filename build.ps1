# Builds dist\Deyla.exe: one file, no console window, the site-like window (Edge WebView2) with its page and icon.
# Run from desktop_agent\ in PowerShell.
$ErrorActionPreference = "Stop"
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Deyla --icon assets\deyla.ico `
  --add-data "deyla_desktop\web;deyla_desktop\web" --add-data "assets\deyla.ico;assets" run.py
Write-Host "Built: $(Resolve-Path dist\Deyla.exe)"
