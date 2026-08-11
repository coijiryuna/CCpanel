# CCPanel

Hosting control panel ala cPanel/aaPanel untuk VPS Ubuntu/Debian. Kelola website (nginx vhost), database (MariaDB/MySQL), SSL (certbot), dan file — dari satu panel web.

**Stack:** Python FastAPI backend + Vue 3 (Vite) frontend. Backend jalan sebagai root (akses sistem), frontend dibuild ke `static/` (minified).

## Fitur v1

- CRUD website: buat/hapus site (folder + nginx vhost), enable/disable
- Tabs proyek ala aaPanel (Static/PHP/Node/Python/Go/Docker): list site difilter per tab, buat site pilih tipe proyek
- Multi-domain per site: pasang/lepas domain alias (update `server_name` vhost otomatis, rollback kalau gagal)
- Proxy project: site bisa punya port + mode proxy penuh — nginx listen di port itu dan forward `location /` ke app di `127.0.0.1:<port>`. Cocok untuk Node.js/Python/Go/Docker app (runner via App Manager, subpath juga didukung)
- PHP per-site: pilih versi PHP (static/8.1/8.2/8.3) per website — pool php-fpm + block fastcgi di vhost dibuat otomatis, switch versi kapan saja
- CRUD database: buat/hapus MariaDB/MySQL DB + user. Form ala cPanel: DB Name, Username (terpisah, default = nama DB), Password (user-defined atau generate), Permission (`localhost`/`%`/IP). Password tersimpan di panel (bisa lihat/copy, default hidden), reset password
- SSL: pasang via certbot (butuh domain + DNS A record), renew manual atau auto-renew via cron (Settings)
- Trash: hapus site → folder pindah ke `/www/trash` (bisa restore/purge)
- File manager: list/upload/hapus file dalam root site (path traversal guard)
- Settings: pasang/hapus auto-renew SSL (crontab root, `0 3 * * *`)
- Auth: single admin, JWT, expired 12 jam
- Frontend: Vue 3 + Vite + vue-router, views/ + components/ terpisah

## Prasyarat (server target)

```bash
# Ubuntu 22.04 / Debian 12
apt update && apt install -y nginx mariadb-server php8.1-fpm php8.2-fpm php8.3-fpm python3-venv python3-pip nodejs npm certbot python3-certbot-nginx
```

## Install

### Cara cepat — via curl (disarankan)

```bash
# VPS Ubuntu 22.04/24.04 / Debian 12/13 (root)
curl -fsSL https://raw.githubusercontent.com/coijiryuna/CCpanel/main/install.sh | sudo bash
```

Skrip otomatis:
1. Deteksi OS + pasang repo PHP yang benar (ondrej/sury/resmi)
2. Install paket: `nginx mariadb-server php8.x-fpm python3-venv nodejs npm certbot`
3. Clone source (kalau belum ada), buat venv, install requirements
4. Build frontend, buat folder `/www/wwwroot` + `/www/trash`
5. Generate password admin + JWT secret otomatis → simpan di `/etc/ccpanel.env` (mode 600)
6. Pasang systemd service `ccpanel`, auto-start

Selesai → tampil di terminal:
```
Login: admin / <password-acak>
Credential tersimpan di /etc/ccpanel.env
```

Akses via SSH tunnel:
```bash
ssh -L 8888:127.0.0.1:8888 user@vps-ip
# buka http://127.0.0.1:8888
```

### Manual — clone + jalankan install.sh

```bash
git clone https://github.com/coijiryuna/CCpanel.git
cd CCpanel
sudo bash install.sh
```

### Manual penuh (tanpa install.sh)

```bash
# 1. Clone / salin project ke /opt/ccpanel
cd /opt/ccpanel

# 2. Backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Frontend (build sekali; ulangi kalau ubah source frontend/)
cd frontend && npm install && npm run build && cd ..

# 4. Folder website + trash
mkdir -p /www/wwwroot /www/trash
```

## Konfigurasi (env var)

| Var | Wajib | Keterangan |
|---|---|---|
| `PANEL_PASSWORD` | wajib kuat | password admin (kalau kosong: generate random, print sekali, lalu set ulang) |
| `PANEL_JWT_SECRET` | opsional | secret JWT (default: random per start) |
| `CCPANEL_CERTBOT_EMAIL` | untuk SSL | email certbot |
| `CCPANEL_MYSQL_ROOT_PASSWORD` | kalau root mysql butuh password | default: socket auth |
| `CCPANEL_NGINX_CONF_DIR` | opsional | default `/etc/nginx/conf.d` (untuk test) |
| `CCPANEL_PHP_FPM_DIR` | opsional | default `/etc/php` (pool php-fpm per versi) |
| `CCPANEL_WWW_ROOT` | opsional | default `/www/wwwroot` |
| `CCPANEL_TRASH_DIR` | opsional | default `/www/trash` |

## Run

```bash
export PANEL_PASSWORD='password-sangat-kuat'
export PANEL_JWT_SECRET=$(openssl rand -hex 32)
export CCPANEL_CERTBOT_EMAIL='admin@domainmu.com'

# wajib root: akses nginx systemctl + mysql socket
sudo -E /opt/ccpanel/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8888
```

Akses via SSH tunnel (panel tidak diexpose ke internet):

```bash
ssh -L 8888:127.0.0.1:8888 user@vps-ip
# buka http://127.0.0.1:8888 di browser lokal
```

## Systemd (opsional, biar auto-start)

`/etc/systemd/system/ccpanel.service` — salin dari `scripts/ccpanel.service`:

```ini
[Unit]
Description=CCPanel
After=network.target

[Service]
Type=simple
EnvironmentFile=-/etc/ccpanel.env
Environment=PANEL_PASSWORD=password-sangat-kuat
Environment=PANEL_JWT_SECRET=secret-panjang-acak
Environment=CCPANEL_CERTBOT_EMAIL=admin@domainmu.com
ExecStart=/opt/ccpanel/.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8888
WorkingDirectory=/opt/ccpanel
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now ccpanel
systemctl status ccpanel
```

Alternatif tanpa systemd — `scripts/ccpanel-ctl`:

```bash
./scripts/ccpanel-ctl start     # background + pidfile + log data/ccpanel.log
./scripts/ccpanel-ctl status
./scripts/ccpanel-ctl restart
./scripts/ccpanel-ctl stop
```

## Firewall

```bash
ufw allow OpenSSH
ufw enable
# JANGAN buka port 8888 — panel akses via SSH tunnel saja
```

## CLI (Go) & client (Node)

Kedua client stdlib-only (tanpa dependency), panggil API panel.

```bash
# Go CLI — build lalu pakai
cd cli/ccpanel && go build -o ccpanel . && ./ccpanel login admin 'PANEL_PASSWORD'
./ccpanel sites
./ccpanel sites create example.com
./ccpanel sites php <id> php8.2
./ccpanel dbs create app_db
./ccpanel backups
./ccpanel dashboard
./ccpanel logs 20

# Node client (tanpa build, butuh Node 18+)
node client/ccpanel.mjs login admin 'PANEL_PASSWORD'
node client/ccpanel.mjs sites
node client/ccpanel.mjs dashboard
```

Env: `CCPANEL_API` (default `http://127.0.0.1:8888`), `CCPANEL_TOKEN` (override login), `CCPANEL_CONFIG` (default `~/.ccpanel.json`, mode 0600).

## Docker

Container panel standalone: nginx + MariaDB + PHP 8.1/8.2/8.3 + uvicorn via supervisord.

```bash
docker compose up -d   # butuh .env: PANEL_PASSWORD, PANEL_JWT_SECRET, CCPANEL_CERTBOT_EMAIL
# panel di http://127.0.0.1:8888 — data SQLite, /www/wwwroot, /www/trash, letsencrypt di volume
```

Catatan: mode container tidak bisa akses service di host (nginx/mysql di dalam image sendiri). Docker tidak bisa dites di lingkungan dev — diuji manual di VPS.

## Keamanan

- Bind `127.0.0.1` — jangan expose `0.0.0.0` tanpa HTTPS + password kuat
- Semua input divalidasi regex whitelist; subprocess tanpa `shell=True`
- `nginx -t` sebelum reload; rollback otomatis kalau gagal
- Password DB tersimpan di panel (bisa lihat/copy, default hidden) — hanya admin panel yang akses
- Hapus site = pindah ke trash (`/www/trash`), bukan permanen

## Uji cepat

```bash
# login
TOKEN=$(curl -s -X POST http://127.0.0.1:8888/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"PANEL_PASSWORD"}' | jq -r .token)

# buat site
curl -s -X POST http://127.0.0.1:8888/api/sites \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"domain":"example.com"}'

# cek nginx serve
curl -H "Host: example.com" http://127.0.0.1
```

## Development

```bash
# backend live-reload
.venv/bin/uvicorn server:app --reload

# frontend hot-reload (proxy API ke backend 8888)
cd frontend && npm run dev
```

## Struktur

```
CCpanel/
├── server.py          # FastAPI: auth + semua endpoint
├── core/
│   ├── validate.py    # sanitasi domain/path/nama-db
│   ├── nginx.py       # vhost template, nginx -t, reload, rollback, trash
│   ├── mysql.py       # create/drop DB + user
│   ├── cert.py        # certbot wrapper (+ renew)
│   └── cron.py        # install/uninstall auto-renew SSL (crontab root)
├── frontend/          # Vue 3 + Vite + vue-router source
│   └── src/
│       ├── router.js      # routes + auth guard
│       ├── App.vue        # shell: sidebar + RouterView
│       ├── views/         # LoginView, SitesView, DatabasesView, TrashView, SettingsView
│       ├── components/    # SiteModal, DbModal, FileManager, AppToast
│       └── composables/   # useToast
├── static/            # hasil build (diserve backend, jangan edit manual)
├── data/              # SQLite (dibuat saat run, jangan di-commit)
├── scripts/           # ccpanel-renew.sh (ditulis cron.py saat install, root-only)
├── cli/ccpanel/       # Go CLI (stdlib-only) + go.mod + main_test.go
├── client/            # ccpanel.mjs — Node.js client (stdlib fetch)
├── Dockerfile         # image: node build frontend → ubuntu + nginx/mariadb/php-fpm
├── docker/            # supervisord.conf untuk container
├── docker-compose.yml
├── requirements.txt
└── plan.md, Ceklist.md
```

## Roadmap (future, YAGNI sekarang)

- Start/Stop/Restart service ccpanel, 
- Multi-server cluster/HA/CDN, 
- Billing/domain registrar API/marketplace plugin.
