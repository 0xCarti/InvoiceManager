param(
    [string]$RepoUrl = "https://github.com/yourusername/InvoiceManager.git",
    [string]$TargetDir = "InvoiceManager"
)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git is required but not installed. Please install git.";
    exit 1
}

if (-not (Test-Path $TargetDir)) {
    Write-Output "Cloning $RepoUrl into $TargetDir"
    git clone $RepoUrl $TargetDir
} else {
    Write-Output "$TargetDir already exists. Pulling latest changes."
    git -C $TargetDir pull
}

Set-Location $TargetDir

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3 is required but not installed.";
    exit 1
}

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Output "Created .env from example. Edit it with your settings."
}

Write-Output "Setup complete. To start the application run:`n.\venv\Scripts\Activate.ps1; python run.py"
