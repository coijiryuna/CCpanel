# Plan: Hosting Control Panel ala cPanel/aaPanel

> Status: rencana implementasi. Target: VPS Ubuntu/Debian fresh install, kelola website (nginx vhost, MariaDB, SSL certbot, file manager) via panel web.

## TL;DR

Bangun hosting control panel (pola aaPanel: Python backend + web frontend) untuk kelola website di VPS: buat/hapus site (folder + nginx vhost), kelola MySQL/MariaDB DB, pasang SSL (certbot), file manager. Backend jalan sebagai root, semua aksi sistem via subprocess argumen-list + validasi ketat.

## Scope — v1 vs Future (penting: jangan campur saat implementasi)

**v1 (dibangun sekarang):**

- OS: Ubuntu 22.04 / Debian 12 fresh install
- Web server: **nginx saja**
- Database: **MariaDB/MySQL saja**
- Security: SSL certbot, path traversal guard, input validation, JWT auth, ufw
- Fitur: CRUD website (folder + nginx vhost), enable/disable site, CRUD database (DB + user, password random), SSL via certbot, file manager (list/upload/hapus)
- Stack: Python 3.10+ (FastAPI, uvicorn, pyjwt, bcrypt) + **Vue 3 + Vite** frontend (build ke `static/`, bundled + minified)
- Auth: single admin, JWT, expired 12 jam
- Akses panel: bind `127.0.0.1:8888` (SSH tunnel), HTTPS via reverse proxy = upgrade (random port + password kuat)

**Future (jangan dikerjakan sekarang, YAGNI):**

- Web server lain: apache, openlitespeed
- DB lain: PostgreSQL, MongoDB, Redis
- PHP: php-fpm per-site, multi-PHP version (v1 = site statis saja, eksplisit!)
- Node.js web frontend, Go CLI tool, Docker containerisasi
- Terminal, Logging/audit trail, FTP/SFTP, WAF
- Multi-user client hosting, backup/restore
- Multi-server cluster, HA, CDN, billing, domain registrar API, marketplace plugin
- Start/Stop/Restart service (ccpanel), monitoring, alerting, metrics, dashboard

## Struktur

```
CCpanel/
├── server.py          # FastAPI: auth + semua endpoint
├── core/
│   ├── __init__.py
│   ├── validate.py    # sanitasi domain/path/nama-db (regex whitelist)
│   ├── nginx.py       # generate vhost template, nginx -t, reload, rollback
│   ├── mysql.py       # create/drop DB + user (argumen list, tanpa shell)
│   └── cert.py        # certbot --non-interactive wrapper
├── data/              # SQLite: users, sites, dbs (gitignore)
├── static/             # hasil build frontend (Vue+Vite, jangan edit manual)
├── frontend/           # source Vue 3 + Vite (npm run build → static/)
├── templates/         # nginx vhost template
├── requirements.txt
├── .gitignore
└── README.md          # install + run di Ubuntu
```

## Skema DB (SQLite)

- `users` (id, username, password_hash, created_at)
- `sites` (id, domain UNIQUE, root_path, vhost_path, enabled, created_at)
- `dbs` (id, site_id FK nullable, db_name UNIQUE, db_user, db_pass, db_host, created_at)

## Steps

### Phase 1 — Skeleton + Auth

1. `server.py`: FastAPI + SQLite init (tabel `users`, `sites`, `dbs`). Seed admin user (bcrypt hash, password dari env var `PANEL_PASSWORD` — wajib kuat, default random + print sekali).
2. Login endpoint → JWT. Middleware `require_auth` pada semua route panel.

### Phase 2 — Website CRUD _(depends Phase 1)_

3. `core/validate.py`: regex domain (punycode + subdomain), path whitelist `/www/wwwroot/`, nama db `[a-z0-9_]{1,64}`.
4. `core/nginx.py`: template vhost (root, server_name, gzip; php-fpm = future). Alur buat site: buat folder + `index.html` default → tulis vhost → `nginx -t` → gagal: hapus file config, return error; sukses: `systemctl reload nginx` → simpan row di SQLite.
5. Endpoint: `POST/GET/DELETE /api/sites`, `POST /api/sites/{id}/enable|disable` (rename `.conf` → `.conf.disabled` + reload).
   - **DELETE ≠ rm -rf permanen.** Alur: hapus vhost → reload → pindah folder root ke `/www/trash/<domain>` (bisa restore). Hapus permanen = aksi terpisah + konfirmasi.

### Phase 3 — Database _(depends Phase 2)_

6. `core/mysql.py`: `mysql` via subprocess argumen-list: create DB, create user@host, GRANT. Form DB (konsep cPanel/aaPanel): DB Name, Username (terpisah, default = nama DB), Password (user-defined atau generate), Permission (`localhost`/`%`/IP). Password disimpan (plaintext, hanya admin panel bisa lihat/copy, default hidden). Endpoint `POST/DELETE /api/dbs`.

### Phase 4 — SSL + File manager _(depends Phase 3)_

7. `core/cert.py`: `certbot certonly --nginx -d domain`, pasang cert path ke vhost, reload. Endpoint `POST /api/sites/{id}/ssl`.
   - **Prasyarat:** paket `python3-certbot-nginx` (bukan cuma `certbot`), domain wajib DNS A record → IP server.
8. File manager: list/upload/hapus file dalam root site (path traversal guard: `resolve()` + prefix check). Endpoint `/api/sites/{id}/files/*`.

### Phase 5 — Frontend _(parallel dengan Phase 3–4)_

9. `static/index.html` + `static/app.js`: login → dashboard (sidebar: Sites, Databases) → modal buat site/db → tombol aksi (enable/disable/ssl/delete→trash) → file manager view. Fetch API dengan Bearer token, tampilkan error dari server.

### Phase 6 — Paket + Docs

10. `requirements.txt` (fastapi, uvicorn, pyjwt, bcrypt). `README.md`: install nginx/mariadb/certbot/python3-certbot-nginx, run `uvicorn server:app --host 127.0.0.1 --port 8888` sebagai root, akses via SSH tunnel, firewall ufw.

## Keamanan (wajib, bukan opsional)

- Semua input divalidasi regex whitelist; subprocess pakai argumen list (tanpa `shell=True`)
- `nginx -t` selalu sebelum reload; rollback hapus config kalau gagal
- Token JWT expired 12 jam; default bind `127.0.0.1` — jangan expose ke internet tanpa HTTPS + password kuat
- Path traversal guard di file manager
- Password DB dihasilkan `secrets` (bukan `random`) atau ditentukan user; disimpan di tabel `dbs` (hanya admin panel yang akses), tampil hidden default

## Verification

1. `python3 -m pytest` atau script self-check: `validate.py` unit test (domain valid/invalid, path traversal)
2. Manual di VPS: login → buat site `test.local` → `curl -H "Host: test.local" localhost` → nginx serve index
3. `nginx -t` lulus setelah tiap operasi; enable/disable mengubah ketersediaan site
4. Buat DB → `mysql -u user -p` login berhasil; hapus DB → hilang
5. SSL: certbot dry-run sukses untuk domain punya DNS A record
6. File manager: upload file → muncul di folder; path `../../etc/passwd` ditolak 400
7. DELETE site → vhost hilang, folder ada di `/www/trash/` (bukan terhapus permanen)

## Decisions

- FastAPI + Vue CDN dipilih: nol build step, satu bahasa deploy, paling sedikit file
- MySQL CLI via subprocess dipilih: hindari dependency ORM eksternal; argumen list cegah injection
- Panel root di `/www/wwwroot/<domain>` (konvensi aaPanel)
- php-fpm pool per-site: DIKECUALIKAN dari scope awal (ponytail: tambah bila butuh multi-PHP-version)
- Trash alih-alih `rm -rf`: cegah kehilangan data permanen (v2: restore + purge terjadwal)

## Further Considerations

1. Auth: JWT simpel vs session cookie — rekomendasi JWT (stateless, frontend terpisah)
2. Domain panel: `127.0.0.1` + random port + SSH tunnel dulu vs subdomain + reverse proxy — mulai tunnel + port random, upgrade nanti
3. Multi-user (client hosting) vs single admin — mulai single admin (YAGNI)

## Service Architecture Details

- Differences in service architectures:

    | Type | Service | Architecture | Port | Scenarios |
    |---|---|---|---|---|
    | Single | Nginx | Standalone | 80/443 | Static websites, file download sites, and lightweight dynamic applications in high-concurrency scenarios |
    | Single | Apache | Standalone | 80/443 | Complex PHP applications (Magento), applications dependent on Apache modules |
    | Single | OpenLiteSpeed | Standalone | 80/443 | WordPress |
    | Multi-WebServer | Nginx + Apache | Nginx (Proxy) -> Apache | Nginx: 80/443<br>Apache: 8288, 8290 | Complex PHP applications (Magento), applications dependent on Apache modules |
    | Multi-WebServer | Nginx + OpenLiteSpeed | Nginx (Proxy) -> OpenLiteSpeed | Nginx: 80/443<br>OpenLiteSpeed: 8188 | WordPress |

- Multi-Services and Corresponding Port Numbers:

    | Service Name | HTTP | HTTPS | phpMyAdmin | Management |
    |---|---|---|---|---|
    | Nginx | 80 | 443 | 888, 887 | - |
    | Apache | 8288 | 8290 | 8289 | - |
    | OpenLiteSpeed | 8188 | 8190 | - | 7080 |

## Docker

| Overview | Container | One-Click Install | Cloud image | Local image | Docker Compose | Network | Volume | Repository | Settings |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |