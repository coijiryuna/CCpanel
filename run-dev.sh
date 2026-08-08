#!/usr/bin/env bash
# Jalankan CCPanel server untuk tes (mode dev, data di /tmp).
# Data sementara, tidak menyentuh sistem asli (nginx/systemd).
set -euo pipefail

cd "$(dirname "$0")"

# --- Konfigurasi tes (semua di /tmp, aman) ---
export CCPANEL_DATA_DIR="${CCPANEL_DATA_DIR:-/tmp/ccp-demo}"
export CCPANEL_SYSTEMD_DIR="$CCPANEL_DATA_DIR/systemd"
export CCPANEL_NGINX_CONF_DIR="$CCPANEL_DATA_DIR/conf"
export CCPANEL_WWW_ROOT="$CCPANEL_DATA_DIR/www"
export CCPANEL_PROJECT_ROOT="$CCPANEL_DATA_DIR/project"
export CCPANEL_TRASH_DIR="$CCPANEL_DATA_DIR/trash"
export CCPANEL_PHP_FPM_DIR="$CCPANEL_DATA_DIR/php"
export PANEL_PASSWORD="${PANEL_PASSWORD:-test123}"
export PANEL_JWT_SECRET="${PANEL_JWT_SECRET:-dev-secret}"
export CCPANEL_WEBSERVER="${CCPANEL_WEBSERVER:-nginx}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8888}"

# --- Setup venv kalau belum ada ---
if [ ! -d .venv ]; then
  echo "==> Buat venv + install deps"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# --- Build frontend kalau belum ada dist ---
if [ ! -d static ]; then
  echo "==> Build frontend"
  (cd frontend && npm install && npm run build)
fi

echo "==> Jalankan CCPanel di http://$HOST:$PORT (password: $PANEL_PASSWORD)"
echo "    Data tes: $CCPANEL_DATA_DIR"
exec .venv/bin/uvicorn server:app --host "$HOST" --port "$PORT" --reload