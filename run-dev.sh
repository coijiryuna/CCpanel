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
export CCPANEL_SITEFEAT_DIR="$CCPANEL_DATA_DIR/sitefeat"
export CCPANEL_APACHE_CONF_DIR="$CCPANEL_DATA_DIR/apache"
export PANEL_PASSWORD="${PANEL_PASSWORD:-test123}"
export PANEL_JWT_SECRET="${PANEL_JWT_SECRET:-dev-secret}"
export CCPANEL_WEBSERVER="${CCPANEL_WEBSERVER:-nginx}"

# --- Mock binary nginx/apachectl/systemctl (dev aman, tak sentuh service asli) ---
_MOCK="$CCPANEL_DATA_DIR/devbin"
mkdir -p "$_MOCK"
for b in nginx apachectl systemctl mysql mariadb php-fpm8.1 php-fpm8.2 php-fpm8.3 php-fpm8.4; do
  if [ ! -x "$_MOCK/$b" ]; then
    printf '#!/bin/sh\nexit 0\n' > "$_MOCK/$b"
    chmod +x "$_MOCK/$b"
  fi
done
# docker mock: ps/images/log/info sukses, action no-op (dev tanpa docker asli)
if [ ! -x "$_MOCK/docker" ]; then
  cat > "$_MOCK/docker" <<'EOF'
#!/bin/sh
case "$1" in
  ps)
    if [ "$2" = "-a" ]; then
      printf 'ID\tIMAGE\tCOMMAND\tCREATED\tSTATUS\tPORTS\tNAMES\nabc123\tnginx:latest\t"nginx -g daemon off;"\t2 days ago\tUp 2 days\t0.0.0.0:8080->80/tcp\tweb-proxy\n'
    else
      printf 'ID\tIMAGE\tCOMMAND\tCREATED\tSTATUS\tPORTS\tNAMES\ndef456\tredis:7\t"redis-server"\t5 hours ago\tUp 5 hours\t6379/tcp\tcache\n'
    fi
    exit 0
    ;;
  images)
    printf 'REPOSITORY\tTAG\tID\tCREATED\tSIZE\nnginx\tlatest\tabc123\t2 days ago\t187MB\nredis\t7\tdef456\t5 hours ago\t110MB\n'
    exit 0
    ;;
  logs) printf 'container log line 1\ncontainer log line 2\n'; exit 0 ;;
  pull) echo "Pulling $2..."; echo "Status: Downloaded newer image for $2"; exit 0 ;;
  run) echo "$2-newcontainerid"; exit 0 ;;
  info) exit 0 ;;
  start|stop|restart|rm) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod +x "$_MOCK/docker"
fi
export PATH="$_MOCK:$PATH"

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