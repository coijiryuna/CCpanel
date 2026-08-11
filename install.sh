#!/usr/bin/env bash
# Install CCPanel di Ubuntu 20.04/22.04/24.04 / Debian 11/12/13 / Linux Mint.
# Jalankan sebagai root: sudo bash install.sh
# Bisa juga langsung via curl (auto-clone kalau source tak ada):
#   curl -fsSL https://raw.githubusercontent.com/coijiryuna/CCpanel/main/install.sh | sudo bash
set -euo pipefail

# --- Self-bootstrap: kalau dijalankan via curl, source tak ada → clone dulu ---
if [ ! -f "$(dirname "$0")/server.py" ]; then
  echo "==> Source CCPanel tidak ditemukan — clone dari GitHub"
  apt install -y git
  _TMP="$(mktemp -d)"
  git clone --depth 1 https://github.com/coijiryuna/CCpanel.git "$_TMP/ccpanel"
  cd "$_TMP/ccpanel"
fi

. /etc/os-release   # set ID, VERSION_CODENAME

echo "==> Deteksi OS: $ID $VERSION_CODENAME ($VERSION_ID)"

# --- Repo PHP yang dibutuhkan ---
# Ubuntu: PPA ondrej/php (php8.1-8.3, tak ada di repo resmi)
# Debian 11/12: repo sury (php8.1-8.3, repo resmi cuma 7.4/8.2)
# Debian 13 / Mint (trixie base): php8.4 ada di repo resmi — tak butuh repo tambahan
setup_php_repos() {
  case "$ID" in
    ubuntu)
      apt install -y software-properties-common
      add-apt-repository -y ppa:ondrej/php
      ;;
    debian)
      case "$VERSION_CODENAME" in
        bookworm|trixie|gigi)
          apt update   # php8.2/8.4 di repo resmi
          ;;
        *)
          # Debian lama (bullseye dkk) — pakai repo sury
          wget -qO /etc/apt/trusted.gpg.d/php.gpg https://packages.sury.org/php/apt.gpg
          echo "deb https://packages.sury.org/php/ $VERSION_CODENAME main" > /etc/apt/sources.list.d/php.list
          apt update
          ;;
      esac
      ;;
    linuxmint)
      case "$VERSION_CODENAME" in
        gigi|virginia)
          apt update   # php8.4 di repo resmi (base trixie)
          ;;
        *)
          # Mint base jammy — sama seperti Ubuntu, butuh ondrej
          apt install -y software-properties-common
          add-apt-repository -y ppa:ondrej/php
          ;;
      esac
      ;;
    *)
      echo "==> OS tak dikenal ($ID) — lewati setup repo PHP, pakai paket bawaan"
      apt update
      ;;
  esac
}

# --- Paket PHP-FPM per rilis ---
case "$ID-$VERSION_CODENAME" in
  ubuntu-*|linuxmint-victoria|linuxmint-faye|linuxmint-una)
    # jammy/noble base: semua versi dari PPA ondrej
    PHP_PKGS="php8.1-fpm php8.2-fpm php8.3-fpm"
    ;;
  debian-bookworm)
    PHP_PKGS="php8.2-fpm"
    ;;
  debian-trixie|linuxmint-gigi|linuxmint-virginia|debian-gigi)
    PHP_PKGS="php8.4-fpm"
    ;;
  *)
    PHP_PKGS="php8.1-fpm php8.2-fpm php8.3-fpm php8.4-fpm"
    ;;
esac

setup_php_repos

echo "==> Install paket sistem ($PHP_PKGS)"
apt install -y nginx mariadb-server $PHP_PKGS python3-venv python3-pip certbot python3-certbot-nginx

APP_DIR="${APP_DIR:-/opt/ccpanel}"
echo "==> Salin project ke $APP_DIR"
mkdir -p "$APP_DIR"
# static/ prebuilt sudah cukup — dashboard/ (source Vue) tidak diperlukan
cp -r server.py api core requirements.txt static scripts "$APP_DIR/"

cd "$APP_DIR"
echo "==> Backend venv"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

##echo "==> Build frontend"
##cd dashboard && npm install && npm run build && cd ..
## Tidak perlu karena sudah build static

echo "==> Folder website + trash"
mkdir -p /www/wwwroot /www/trash

echo "==> Systemd service + env"
# Secret otomatis kalau belum diset (mis. install ulang)
if [ -z "${PANEL_PASSWORD:-}" ]; then PANEL_PASSWORD="$(openssl rand -base64 24)"; fi
if [ -z "${PANEL_JWT_SECRET:-}" ]; then PANEL_JWT_SECRET="$(openssl rand -hex 32)"; fi
if [ -z "${CCPANEL_CERTBOT_EMAIL:-}" ]; then CCPANEL_CERTBOT_EMAIL="admin@$(hostname -f 2>/dev/null || echo localhost)"; fi

# EnvironmentFile — isi rahasia, mode 600
cat > /etc/ccpanel.env <<EOF
PANEL_PASSWORD=$PANEL_PASSWORD
PANEL_JWT_SECRET=$PANEL_JWT_SECRET
CCPANEL_CERTBOT_EMAIL=$CCPANEL_CERTBOT_EMAIL
EOF
chmod 600 /etc/ccpanel.env

# Unit systemd (ditulis langsung — tak bergantung file scripts/ccpanel.service)
cat > /etc/systemd/system/ccpanel.service <<EOF
[Unit]
Description=CCPanel
After=network.target

[Service]
Type=simple
EnvironmentFile=-/etc/ccpanel.env
ExecStart=$APP_DIR/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8888
WorkingDirectory=$APP_DIR
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now ccpanel
sleep 2
systemctl --no-pager --lines=5 status ccpanel

# Sisa rahasia tak boleh di-echo penuh — tampilkan sekali lalu simpan
echo ""
echo "=================================================="
echo "Selesai. Panel jalan: http://127.0.0.1:8888"
echo "Login: admin / $PANEL_PASSWORD"
echo "Credential tersimpan di /etc/ccpanel.env (mode 600)"
echo "=================================================="
echo "Akses remote via SSH tunnel:"
echo "  ssh -L 8888:127.0.0.1:8888 user@vps-ip"
