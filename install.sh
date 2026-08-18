#!/usr/bin/env bash
# Install CCPanel di Ubuntu 20.04/22.04/24.04 / Debian 11/12/13 / Linux Mint.
# Jalankan sebagai root: sudo bash install.sh
# Bisa juga langsung via curl (auto-clone kalau source tak ada):
#   curl -fsSL https://raw.githubusercontent.com/coijiryuna/CCpanel/main/install.sh | sudo bash
# Options:
#   --fresh    Uninstall all CCPanel packages first (nginx, apache2, openlitespeed, mariadb, php*, certbot, etc.)
#   --help     Show this help
set -euo pipefail

# --- Parse arguments ---
FRESH_INSTALL=false
for arg in "$@"; do
  case "$arg" in
    --fresh) FRESH_INSTALL=true ;;
    --help)
      echo "Usage: $0 [--fresh] [--help]"
      echo "  --fresh   Uninstall all CCPanel packages before installing"
      echo "  --help    Show this help"
      exit 0
      ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

# --- Fresh install: uninstall all CCPanel packages first ---
if [ "$FRESH_INSTALL" = true ]; then
  echo "==> FRESH INSTALL: Uninstalling all CCPanel packages..."
  # Stop services first
  systemctl stop ccpanel 2>/dev/null || true
  systemctl stop nginx 2>/dev/null || true
  systemctl stop apache2 2>/dev/null || true
  systemctl stop lsws 2>/dev/null || true
  systemctl stop mariadb 2>/dev/null || true
  systemctl stop mysql 2>/dev/null || true
  systemctl stop php8.1-fpm 2>/dev/null || true
  systemctl stop php8.2-fpm 2>/dev/null || true
  systemctl stop php8.3-fpm 2>/dev/null || true
  systemctl stop php8.4-fpm 2>/dev/null || true
  
  # Purge packages (remove config files too) - mariadb first to avoid update-alternatives error
  DEBIAN_FRONTEND=noninteractive apt purge -y mariadb-server mariadb-client mariadb-common 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y mysql-server mysql-client mysql-common 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y nginx nginx-common nginx-core 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y apache2 apache2-bin apache2-data apache2-utils 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y openlitespeed lsphp* 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y php8.1-fpm php8.2-fpm php8.3-fpm php8.4-fpm 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y php8.1-cli php8.2-cli php8.3-cli php8.4-cli 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y php8.1-common php8.2-common php8.3-common php8.4-common 2>/dev/null || true
  DEBIAN_FRONTEND=noninteractive apt purge -y certbot python3-certbot-nginx 2>/dev/null || true
  apt autoremove -y 2>/dev/null || true
  apt autoclean 2>/dev/null || true
  
  # Remove config directories (after purge)
  rm -rf /etc/apache2 /usr/local/lsws /etc/php 2>/dev/null || true
  rm -rf /etc/nginx/sites-enabled/* /etc/nginx/conf.d/* 2>/dev/null || true
  rm -rf /etc/mysql/mariadb.conf.d/* 2>/dev/null || true  rm -rf /www/wwwroot /www/trash /www/project /www/wwwlogs /www/server 2>/dev/null || true
  rm -f /etc/ccpanel.env 2>/dev/null || true
  systemctl daemon-reload
  
  echo "==> Fresh uninstall complete"
fi

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
# Install mariadb-server first with noninteractive to avoid update-alternatives error
DEBIAN_FRONTEND=noninteractive apt install -y -o Dpkg::Options::="--force-confmiss" mariadb-server 2>/dev/null || true
DEBIAN_FRONTEND=noninteractive apt install -y -o Dpkg::Options::="--force-confmiss" nginx $PHP_PKGS python3-venv python3-pip certbot python3-certbot-nginx

# --- Install Apache (backend port 8288) ---
echo "==> Install Apache (backend port 8288)"
apt install -y apache2

# Hentikan Apache dulu dan ubah port ke 8288 SEBELUM install mod-fcgid agar tidak bentrok dengan Nginx di port 80
systemctl stop apache2 2>/dev/null || true
sed -i '/^Listen 80$/d' /etc/apache2/ports.conf
sed -i '/^Listen 443$/d' /etc/apache2/ports.conf
if ! grep -q "^Listen 8288" /etc/apache2/ports.conf; then
  echo "Listen 8288" >> /etc/apache2/ports.conf
fi
a2dissite 000-default 2>/dev/null || true
rm -f /etc/apache2/sites-enabled/000-default.conf 2>/dev/null || true

# Sekarang aman untuk menginstalnya tanpa memicu error port 80
apt install -y libapache2-mod-fcgid || echo "==> WARNING: libapache2-mod-fcgid could not be installed, skipping."

# Enable modul yang dibutuhkan
a2enmod proxy proxy_http proxy_fcgi rewrite headers remoteip deflate ssl 2>/dev/null || true

# Create Apache vhost directory for panel
mkdir -p /etc/apache2/sites-available /etc/apache2/sites-enabled
mkdir -p /www/server/panel/vhost/apache/extension

# --- Install OpenLiteSpeed (backend port 8188) ---
echo "==> Install OpenLiteSpeed (backend port 8188)"
# Add OpenLiteSpeed repo (manual — script resmi kadang gagal di Debian baru)
if [ "$ID" = "ubuntu" ] || [ "$ID" = "debian" ] || [ "$ID" = "linuxmint" ]; then
  if [ ! -f /etc/apt/sources.list.d/lst_debian_repo.list ]; then
    # 1. Download and save the LiteSpeed repository GPG key
    sudo wget -O /usr/share/keyrings/litespeed-archive-keyring.gpg https://rpms.litespeedtech.com/debian/lst_repo.gpg
    # 2. Add the repository explicitly referencing the downloaded key
    echo "deb [signed-by=/usr/share/keyrings/litespeed-archive-keyring.gpg] https://rpms.litespeedtech.com/debian/ $VERSION_CODENAME main" | sudo tee /etc/apt/sources.list.d/lst_debian_repo.list
    # 3. Update APT package lists
    sudo apt update 2>/dev/null || true
  fi
  # OLS optional — kalau gagal install, panel tetap jalan (backend engine saja)
  if apt-cache show openlitespeed >/dev/null 2>&1; then
    # Install lsphp based on detected PHP_PKGS
    LS_PHP_PKGS=""
    for pkg in $PHP_PKGS; do
      # Extract major.minor version from phpX.Y-fpm
      if [[ $pkg =~ php([0-9]+\.[0-9]+)-fpm ]]; then
        PHP_VERSION_SHORT="${BASH_REMATCH[1]//./}" # e.g., 8.1 -> 81
        LS_PHP_PKGS+="lsphp${PHP_VERSION_SHORT} lsphp${PHP_VERSION_SHORT}-common lsphp${PHP_VERSION_SHORT}-mysql "
      fi
    done
    apt install -y openlitespeed $LS_PHP_PKGS 2>/dev/null || apt install -y openlitespeed 2>/dev/null || true
  else
    echo "==> WARNING: openlitespeed tidak tersedia di repo — lewati (backend OLS nonaktif)"
  fi
fi
# Create OLS vhost directory for panel
mkdir -p /usr/local/lsws/conf/vhosts
mkdir -p /www/server/panel/vhost/litespeed/extension

cleanup_ols_example() {
  local conf_dir="/usr/local/lsws/conf"
  local httpd_conf="$conf_dir/httpd_config.conf"
  local example_dir="$conf_dir/vhosts/Example"
  local backups=(
    "$conf_dir/httpd_config.conf0"
    "$conf_dir/httpd_config.conf0,v"
    "$conf_dir/httpd_config.conf.txt"
  )

  systemctl stop lsws 2>/dev/null || true
  rm -rf "$example_dir" 2>/dev/null || true

  if [ -f "$httpd_conf" ]; then
    sed -i '/^[[:space:]]*virtualHost Example{/,/^[[:space:]]*}[[:space:]]*$/d' "$httpd_conf"
    sed -i '/^[[:space:]]*map[[:space:]]\+Example[[:space:]]\+\*/d' "$httpd_conf"
    sed -i 's/8088/8188/g' "$httpd_conf"
  fi

  for b in "${backups[@]}"; do
    rm -f "$b" 2>/dev/null || true
  done
}

cleanup_ols_example

# Hard reset OLS port in case repo config still carries 8088
if [ -d /usr/local/lsws/conf ]; then
  if grep -RIl "8088" /usr/local/lsws/conf 2>/dev/null; then
    grep -RIl "8088" /usr/local/lsws/conf 2>/dev/null | xargs -r sed -i 's/8088/8188/g'
  fi
fi

# Enable and start Apache and OpenLiteSpeed services
# Apache is configured to listen only on 8288 (not 80), so it won't conflict with nginx
systemctl enable --now apache2 2>/dev/null || true
systemctl enable --now lsws 2>/dev/null || true

APP_DIR="${APP_DIR:-/opt/ccpanel}"
echo "==> Salin project ke $APP_DIR"
mkdir -p "$APP_DIR"
# static/ prebuilt sudah cukup — dashboard/ (source Vue) tidak diperlukan
cp -r server.py api core requirements.txt static scripts "$APP_DIR/"

cd "$APP_DIR"
echo "==> Backend venv"
# Try to use python3.12, then python3.11, then python3
PYTHON_BIN=""
if command -v python3.12 &> /dev/null; then
  PYTHON_BIN="python3.12"
elif command -v python3.11 &> /dev/null; then
  PYTHON_BIN="python3.11"
else
  PYTHON_BIN="python3"
fi
echo "Menggunakan $PYTHON_BIN untuk venv"

# MENJADI:
"$PYTHON_BIN" -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install --force-reinstall "fastapi>=0.110.0" "pydantic>=2.7.0" uvicorn
.venv/bin/pip install -r requirements.txt

##echo "==> Build frontend"
##cd dashboard && npm install && npm run build && cd ..
## Tidak perlu karena sudah build static

# Tambahkan pembuatan folder data secara eksplisit
mkdir -p /www/wwwroot /www/trash /www/project /www/wwwlogs /etc/nginx/conf.d "$APP_DIR/data"

# Create www user and group if they don't exist
if ! getent group www > /dev/null; then
  groupadd www
fi
if ! getent passwd www > /dev/null; then
  useradd -r -g www -s /sbin/nologin www
fi

# Set ownership for /www directory
chown -R www:www /www

# Install sudo
apt install -y sudo

# Add www user to sudoers (no password)
echo "www ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

echo "==> Systemd service + env"
# Upgrade: pakai credential lama kalau ada (jangan generate ulang)
if [ -f /etc/ccpanel.env ]; then
  echo "==> /etc/ccpanel.env ditemukan — pertahankan credential lama"
  set -a; . /etc/ccpanel.env; set +a
fi
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
# Bind ke 0.0.0.0 agar bisa diakses via QEMU port forwarding / SSH tunnel
cat > /etc/systemd/system/ccpanel.service <<EOF
[Unit]
Description=CCPanel
After=network.target

[Service]
Type=simple
EnvironmentFile=-/etc/ccpanel.env
ExecStart=$APP_DIR/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8888
WorkingDirectory=$APP_DIR
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

# Update admin password in database (create admin if not exists)
echo "==> Update admin password in database..."
CCPANEL_DATA_DIR="$APP_DIR/data" PANEL_PASSWORD="$PANEL_PASSWORD" $APP_DIR/.venv/bin/python3 -c "
import bcrypt, sqlite3, os
from pathlib import Path
from datetime import datetime, timezone
data_dir = Path(os.environ.get('CCPANEL_DATA_DIR'))
data_dir.mkdir(parents=True, exist_ok=True)
db_path = data_dir / 'ccpanel.db'
conn = sqlite3.connect(db_path)
# Ensure users table exists
conn.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'client',
        created_at TEXT NOT NULL
    )
''')
pw_hash = bcrypt.hashpw(os.environ.get('PANEL_PASSWORD', '').encode(), bcrypt.gensalt()).decode()
conn.execute('''
    INSERT OR REPLACE INTO users (username, password_hash, role, created_at)
    VALUES (?, ?, 'admin', ?)
''', ('admin', pw_hash, datetime.now(timezone.utc).isoformat()))
conn.commit()
conn.close()
print('Admin password updated in database')
"

# Start service AFTER database is ready
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
