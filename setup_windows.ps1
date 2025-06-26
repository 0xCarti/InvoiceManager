# Setup script for InvoiceManager on Windows using PowerShell
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

$secret = Read-Host "Flask SECRET_KEY"
$adminEmail = Read-Host "Admin email"
$adminPass = Read-Host "Admin password"
$gst = Read-Host "GST number (optional)"

@"`nSECRET_KEY=$secret`nADMIN_EMAIL=$adminEmail`nADMIN_PASS=$adminPass`nGST=$gst`n"@ | Out-File -Encoding UTF8 .env

python -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python scripts/init_app.py

Write-Host "Setup complete. Activate with 'venv\\Scripts\\Activate.ps1' before running the app."
