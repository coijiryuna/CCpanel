# CCPanel — Daftar API

Total: **52 endpoint**. Base URL: `http://<server>:8888`. Semua endpoint (kecuali `/api/login`) wajib header `Authorization: Bearer <token>`.

- **Client vs admin**: client hanya lihat/ubah resource miliknya (`owner_id`). Admin bebas semua.
- **Aksi permanen** (trash purge, backup delete, terminal exec, reset password): tidak bisa dibalik.

## Auth & Dashboard

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| POST | `/api/login` | Login (username+password) → token JWT (HS256, 12 jam) | publik |
| GET | `/api/me` | Info user yang login (username, role) | login |
| GET | `/api/dashboard` | Statistik panel: jumlah site/DB/FTP, total ukuran, status tiap site | login (client hanya site miliknya) |

## Users (manajemen akun)

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/users` | Daftar semua user. DataTables: `start`, `length`, `draw`, `search`, `order_col` (0/1/2/3 atau nama kolom), `order_dir` (asc/desc). `length>0` → `{draw, recordsTotal, recordsFiltered, data}` | admin |
| POST | `/api/users` | Buat user baru (username, password 6-128, role admin/client) | admin |
| DELETE | `/api/users/{id}` | Hapus user (site jadi tak bertuan). Admin utama & diri sendiri tak bisa dihapus | admin |
| POST | `/api/users/{id}/reset-password` | Reset password user → return password baru random | admin |

## Sites (website)

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| POST | `/api/sites` | Buat site: validasi domain, buat folder root + vhost, `nginx -t` + reload | login |
| GET | `/api/sites` | Daftar site (+ info app: tipe, port, entry, subpath, state live). DataTables: `start`, `length`, `draw`, `search`, `order_col` (0/1/2/3 atau nama kolom), `order_dir` | login |
| POST | `/api/sites/{id}/enable` | Aktifkan site (rename vhost `.disabled` → aktif) | login |
| POST | `/api/sites/{id}/disable` | Nonaktifkan site | login |
| POST | `/api/sites/{id}/waf` | Toggle WAF on/off (nginx-only, sisipkan rules `if` ke vhost) | login |
| PUT | `/api/sites/{id}/php` | Ganti PHP version: `static`/`php8.1`/`php8.2`/`php8.3` (nginx-only, update pool + fastcgi block) | login |
| DELETE | `/api/sites/{id}` | Hapus site: vhost + folder ke trash (bukan permanen). Bersihkan pool PHP + unit app | login |

## Apps (app runner: Node/Python/Go/Docker)

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/sites/{id}/apps` | Status app per-site (state: active/inactive/stopped/running). DataTables: `start`, `length`, `draw`, `search`, `order_col`, `order_dir` | login |
| POST | `/api/sites/{id}/apps` | Pasang app: `app_type` (node/python/go/docker), `port`, `entry`, `subpath`. Tulis systemd unit (node/python/go) atau compose up (docker) + proxy subpath ke vhost. 1 app per site, nginx-only | login |
| POST | `/api/sites/{id}/apps/action` | Body `{action}`: `start`/`stop`/`restart`/`status` → systemctl atau docker compose | login |
| GET | `/api/sites/{id}/apps/log` | Tail log app: `journalctl -u` (systemd) atau `compose logs` (docker). Param `lines` (default 100) | login |
| PUT | `/api/sites/{id}/apps` | Update app: tulis ulang unit + proxy (entry default: node=index.js, python=app:app, go=app, docker=docker-compose.yml) | login |
| DELETE | `/api/sites/{id}/apps` | Hapus app: stop + disable unit / compose down + hapus block proxy. File project tetap | login |

## Vhost Config

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/sites/{id}/vhost-config` | Ambil isi file config vhost + path + engine | login |
| PUT | `/api/sites/{id}/vhost-config` | Simpan config → test (`nginx -t`) → reload. **Rollback otomatis kalau test gagal** | login |

## Databases

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| POST | `/api/dbs` | Buat DB: `db_name`, `db_user`, `password`, `host` (localhost/%/IP), `db_type` (mysql/mariadb/pgsql), `site_id` (opsional) | login |
| GET | `/api/dbs` | Daftar DB (client hanya miliknya). DataTables: `start`, `length`, `draw`, `search`, `db_type`, `order_col`, `order_dir` | login |
| POST | `/api/dbs/{id}/reset-password` | Reset password DB → password baru random | login |
| DELETE | `/api/dbs/{id}` | Hapus DB (drop db + user) | login |

## SSL

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| POST | `/api/sites/{id}/ssl` | Pasang SSL via certbot untuk domain site | login |
| POST | `/api/ssl/renew` | Renew semua cert mendekati expiry (manual, sama seperti cron) | admin |

## Settings

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/settings/webserver` | Engine web server aktif (nginx/apache/litespeed) | admin |
| POST | `/api/settings/webserver` | Ganti engine global (site baru saja; site lama tetap) | admin |
| GET | `/api/settings/database` | Engine DB aktif | admin |
| POST | `/api/settings/database` | Ganti engine DB global | admin |

## Cron (auto-renew SSL)

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/cron/status` | Status cron auto-renew | admin |
| POST | `/api/cron/install` | Pasang script + crontab auto-renew (idempoten) | admin |
| POST | `/api/cron/uninstall` | Hapus crontab + script (idempoten) | admin |

## Trash

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/trash` | Daftar item trash (nama, size, mtime). DataTables: `start`, `length`, `draw`, `search`, `order_col`, `order_dir` | admin |
| POST | `/api/trash/{name}/restore` | Restore site: folder balik ke wwwroot + tulis vhost + row site baru | admin |
| DELETE | `/api/trash/{name}` | Hapus **PERMANEN** folder trash — tidak bisa dibatalkan | admin |

## Logs & Terminal

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/logs` | Audit trail aksi (limit 1-500, default 100). DataTables: `start`, `length`, `draw`, `search`, `order_col`, `order_dir` (default desc) | admin |
| POST | `/api/terminal/exec` | Eksekusi shell sebagai root. Ada blacklist command berbahaya | admin |

## Backup

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/backups` | Daftar file backup (site tar.gz + DB sql.gz). DataTables: `start`, `length`, `draw`, `search`, `order_col`, `order_dir` | admin |
| POST | `/api/backups/site/{id}` | Backup folder site → tar.gz | admin |
| POST | `/api/backups/db/{id}` | Backup DB → sql.gz (mysqldump) | admin |
| POST | `/api/backups/{name}/restore` | Restore: site → extract + vhost + row baru; DB → butuh DB sudah dibuat dulu | admin |
| DELETE | `/api/backups/{name}` | Hapus file backup (nama divalidasi anti traversal) | admin |

## FTP

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/ftp` | Daftar akun FTP (+ domain site). DataTables: `start`, `length`, `draw`, `search`, `order_col`, `order_dir` | login |
| POST | `/api/ftp` | Buat akun FTP untuk site (`username`, `password` opsional, `site_id`) | login |
| POST | `/api/ftp/{id}/reset-password` | Reset password FTP → password baru | login |
| DELETE | `/api/ftp/{id}` | Hapus akun FTP | login |

## File Manager

| Method | Endpoint | Fungsi | Akses |
|---|---|---|---|
| GET | `/api/sites/{id}/files` | List isi folder site (param `path`, traversal guard: wajib dalam root) | login |
| POST | `/api/sites/{id}/files` | Upload file (multipart `file` + param `path`. Nama disanitasi anti `../`) | login |
| DELETE | `/api/sites/{id}/files` | Hapus file/folder (param `path`. Root tak bisa dihapus) | login |
