#!/usr/bin/env bash
set -e

REPO_URL=${1:-"https://github.com/yourusername/InvoiceManager.git"}
TARGET_DIR=${2:-"InvoiceManager"}

if ! command -v git >/dev/null 2>&1; then
    echo "git is required but not installed. Please install git." >&2
    exit 1
fi

if [ ! -d "$TARGET_DIR" ]; then
    echo "Cloning $REPO_URL into $TARGET_DIR"
    git clone "$REPO_URL" "$TARGET_DIR"
else
    echo "Directory $TARGET_DIR exists. Pulling latest changes."
    git -C "$TARGET_DIR" pull
fi

cd "$TARGET_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required but not installed. Please install Python 3." >&2
    exit 1
fi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from example. Edit it with your settings."
fi

echo "Setup complete. To start the application run:\nsource venv/bin/activate && python run.py"
