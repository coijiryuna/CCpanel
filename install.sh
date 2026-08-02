#!/usr/bin/env bash
# Install CCPanel di Ubuntu 22.04 / Debian 12 fresh install.
# Jalankan sebagai root: sudo bash install.sh
set -euo pipefail

echo "==> Install paket sistem"
apt update
apt install -y nginx mariadb-server php8.1-fpm php8.2-fpm php8.3-fpm python3-venv python3-pip nodejs npm certbot python3-certbot-nginx

APP_DIR="${APP_DIR:-/opt/ccpanel}"
echo "==> Salin project ke $APP_DIR"
mkdir -p "$APP_DIR"
cp -r server.py core requirements.txt frontend static "$APP_DIR/"

cd "$APP_DIR"
echo "==> Backend venv"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

echo "==> Build frontend"
cd frontend && npm install && npm run build && cd ..

echo "==> Folder website + trash"
mkdir -p /www/wwwroot /www/trash

echo ""
echo "Selesai. Langkah berikutnya:"
echo "  1. export PANEL_PASSWORD='password-kuat' PANEL_JWT_SECRET=\$(openssl rand -hex 32) CCPANEL_CERTBOT_EMAIL='admin@domainmu.com'"
echo "  2. sudo -E $APP_DIR/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8888"
echo "  3. Akses via SSH tunnel: ssh -L 8888:127.0.0.1:8888 user@vps-ip"
