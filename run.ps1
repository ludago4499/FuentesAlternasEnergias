# GDMTH Solar Analyzer — Windows PowerShell startup script
# Usage: .\run.ps1

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir   = Join-Path $ScriptDir ".venv"

# Create venv if absent
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv $VenvDir
}

# Activate
$ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
& $ActivateScript

# Install deps
Write-Host "Installing dependencies..." -ForegroundColor Cyan
pip install --upgrade pip -q
pip install -r (Join-Path $ScriptDir "requirements.txt") -q

# Launch
Write-Host "Starting Streamlit app at http://localhost:8501" -ForegroundColor Green
streamlit run (Join-Path $ScriptDir "app\main.py") `
    --server.port 8501 `
    --theme.base "light" `
    --theme.primaryColor "#FFD400" `
    --theme.backgroundColor "#F5F0E1" `
    --theme.secondaryBackgroundColor "#FAF6EB" `
    --theme.textColor "#15151A"
