#!/usr/bin/env bash
# Setup script for InvoiceManager on Linux/macOS
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

read -p "Flask SECRET_KEY: " SECRET_KEY
read -p "Admin email: " ADMIN_EMAIL
read -p "Admin password: " ADMIN_PASS
read -p "GST number (optional): " GST

cat > .env <<ENV
SECRET_KEY=$SECRET_KEY
ADMIN_EMAIL=$ADMIN_EMAIL
ADMIN_PASS=$ADMIN_PASS
GST=$GST
ENV

python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python scripts/init_app.py

echo "Setup complete. Activate with 'source venv/bin/activate' before running the app."
