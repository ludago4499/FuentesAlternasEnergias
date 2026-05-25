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
    --theme.primaryColor "#0039A6" `
    --theme.backgroundColor "#FFFFFF" `
    --theme.secondaryBackgroundColor "#F0F4FF" `
    --theme.textColor "#1A1A2E"
