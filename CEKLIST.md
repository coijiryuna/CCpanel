# Ceklist Implementasi CCPanel

> Centang saat selesai. Ikuti urutan phase — tiap phase bergantung phase sebelumnya kecuali ditandai.

## Phase 1 — Skeleton + Auth
- [x] `core/__init__.py` dibuat
- [x] `server.py`: FastAPI app + SQLite init (tabel `users`, `sites`, `dbs`)
- [x] Seed admin user (bcrypt hash, password dari env `PANEL_PASSWORD`, wajib kuat, default random + print sekali)
- [x] Endpoint `POST /api/login` → JWT
- [x] Middleware `require_auth` (JWT expired 12 jam) di semua route panel
- [x] Static file serve (`static/`)

## Phase 2 — Website CRUD
- [x] `core/validate.py`: regex domain (punycode + subdomain)
- [x] `core/validate.py`: regex nama db `[a-z0-9_]{1,64}`
- [x] `core/validate.py`: path whitelist `/www/wwwroot/`
- [x] `core/nginx.py`: template vhost (root, server_name, gzip; php-fpm = future)
- [x] `core/nginx.py`: alur buat site — folder + `index.html` default → tulis vhost → `nginx -t` → gagal rollback, sukses reload
- [x] `POST /api/sites` (buat site)
- [x] `GET /api/sites` (list site)
- [x] `POST /api/sites/{id}/enable|disable` (rename `.conf` → `.conf.disabled` + reload)
- [x] `DELETE /api/sites` — trash: hapus vhost + reload + pindah folder ke `/www/trash/<domain>` (BUKAN `rm -rf`)

## Phase 3 — Database
- [x] `core/mysql.py`: create DB + user@localhost + GRANT via subprocess argumen-list
- [x] Password DB: `secrets` 16 char, tampil sekali di response, tidak disimpan plaintext
- [x] Simpan row di tabel `dbs`
- [x] `POST /api/dbs`
- [x] `DELETE /api/dbs`

## Phase 4 — SSL + File Manager
- [x] `core/cert.py`: `certbot certonly --nginx -d domain` → pasang cert ke vhost → reload
- [x] `POST /api/sites/{id}/ssl`
- [x] File manager: list file dalam root site
- [x] File manager: upload file
- [x] File manager: hapus file
- [x] Path traversal guard: `resolve()` + prefix check (path `../../etc/passwd` ditolak 400)

## Phase 5 — Frontend (parallel dengan Phase 3–4)
- [x] Vue 3 + Vite (`frontend/`, build ke `static/`)
- [x] `static/index.html`: layout + login view
- [x] `src/api.js`: login → simpan token (localStorage)
- [x] Dashboard: sidebar (Sites, Databases)
- [x] Sites view: list + modal buat site + tombol aksi (enable/disable/ssl/delete→trash)
- [x] Databases view: list + modal buat db + tombol hapus
- [x] File manager view: list/upload/hapus file per site
- [x] Fetch API pakai Bearer token, tampilkan error dari server

## Phase 6 — Paket + Docs
- [x] `requirements.txt` (fastapi, uvicorn, pyjwt, bcrypt)
- [x] `.gitignore` (data/, `__pycache__`, .env, node_modules/)
- [x] `templates/` vhost template terpisah (atau string di `core/nginx.py`)
- [x] `README.md`: install nginx/mariadb/certbot/python3-certbot-nginx
- [x] `README.md`: run `uvicorn server:app --host 127.0.0.1 --port 8888` sebagai root
- [x] `README.md`: akses via SSH tunnel, firewall ufw
- [x] `install.sh`: script install Ubuntu/Debian
- [x] `test_validate.py`: unit test validasi + path traversal

## Verification (wajib lulus sebelum nyerah)
- [x] Unit test `validate.py`: domain valid/invalid, path traversal ditolak (7 passed)
- [x] `nginx -t` lulus setelah tiap operasi site (alur tes dengan fake nginx + env override)
- [x] Enable/disable mengubah ketersediaan site
- [x] Buat DB → user+grant dibuat; hapus → DROP DATABASE + DROP USER (fake mysql record SQL)
- [x] DELETE site → folder ada di `/www/trash/` (bukan terhapus permanen)
- [ ] SSL: certbot real + domain DNS A record — **butuh VPS, skip di lokal**
- [x] File manager: upload muncul di folder; `../../etc/passwd` ditolak 400
- [x] Regression penuh: auth, site lifecycle, files, db, trash, frontend serve
- [x] Fix: mount StaticFiles dipindah ke akhir (POST API tadinya 405)
- [x] Fix: SPA fallback — vue-router history mode (`/sites` refresh tadinya 404)
- [x] Form DB ala cPanel: DB Name + Username + Password (user-defined/generate) + Permission (localhost/%/IP)
- [x] Password DB tersimpan (bisa lihat/copy, default hidden), reset password persist
- [x] Frontend dipecah: views/ + components/ + router.js (vue-router, lazy-load)

## Future features (trash restore/purge + SSL auto-renew)
- [x] `core/nginx.py`: `trash_items()`, `restore_site()` (parse nama + timestamp suffix), `purge_site()` (guard traversal)
- [x] Endpoint trash: `GET /api/trash`, `POST /api/trash/{name}/restore`, `DELETE /api/trash/{name}`
- [x] Trash view + nav sidebar (restore/purge dengan konfirmasi)
- [x] `core/cert.py`: `renew_all()` (`certbot renew --nginx`)
- [x] Endpoint `POST /api/ssl/renew` + tombol "Renew SSL" di sidebar
- [x] `core/cron.py`: install/uninstall cron auto-renew SSL (script root-only 0700 + crontab `0 3 * * *` + lock + log)
- [x] Endpoint cron: `GET /api/cron/status`, `POST /api/cron/install`, `POST /api/cron/uninstall`
- [x] Settings view + route `/settings` + nav (pasang/hapus auto-renew)
- [x] E2E browser: trash→restore→purge→renew→cron install/uninstall semua jalan
- [x] Fix: `crontab -` baca stdin → hang; pakai `subprocess.run(input=...)`
- [x] Fix: `_current()` treat stderr kosong + exit 1 sebagai "belum ada crontab"
- [x] Fix: script cron PATH eksplisit (cron environment PATH minimal)

## Future YAGNI (belum dikerjakan, satu per satu)
- [x] Logging/audit trail (tabel `audit_log`, helper `_log()`, endpoint `GET /api/logs?limit=`, LogsView + route `/logs` + nav, semua aksi admin tercatat: login, site, db, ssl, trash, cron)
- [x] Terminal (web-based shell: `core/terminal.py` `bash -c` + timeout 15s + deny list editor/REPL/ssh/tail -f + output cap, `POST /api/terminal/exec`, TerminalView + route `/terminal` + nav, semua exec dicatat audit `terminal.exec`)
- [x] Backup/restore site + DB (`core/backup.py` tar.gz/mysqldump+gzip, traversal guard, `GET /api/backups`, `POST /api/backups/site|db/{id}`, `POST /api/backups/{name}/restore` (site: extract+`activate_site`; db: gzip -dc | mysql), `DELETE /api/backups/{name}`, BackupView + route `/backup` + nav; E2E: backup site+DB → hapus site → restore site (folder+vhost kembali) → restore DB → hapus backup semua jalan)
- [x] FTP/SFTP (FTP vsftpd virtual users selesai: `core/ftp.py` user_db via db_load atomic temp+rename, tabel `ftp_accounts`, `GET/POST /api/ftp`, `POST /api/ftp/{id}/reset-password`, `DELETE /api/ftp/{id}`, FtpView + route `/ftp` + nav, audit ftp.create/reset-password/delete; E2E semua jalan. **SFTP deferred** — butuh user sistem + sshd config, invasif, tanpa spek)
- [x] WAF (selesai: `core/waf.py` rules nginx `if ($request_uri ~*) return 403` — SQLi/XSS/traversal/cmd-injection, toggle per-site tulis `waf.d/{domain}.conf` + sisip `include` ke vhost lama otomatis + `nginx -t` + reload, kolom `waf_enabled` + migrasi ALTER, `POST /api/sites/{id}/waf`, tombol WAF ON/OFF di SitesView, audit waf.enable/disable; E2E toggle ON→OFF jalan)
- [x] Multi-user client hosting (selesai: role admin/client di tabel users + migrasi ALTER, `owner_id` di sites+dbs + migrasi, `require_auth` return dict user + `require_admin` guard, filter owner di sites/dbs/ftp/files, `_check_site_access`/`_check_db_access`/`_check_ftp_access` 403, CRUD users admin-only `GET/POST /api/users` + `DELETE /api/users/{id}` + `POST /api/users/{id}/reset-password`, UsersView + route `/users`, nav admin-only (Trash/Logs/Terminal/Backup/Settings/Users/Renew SSL), role disimpan localStorage; E2E: client login cuma lihat nav terbatas + site sendiri, 403 akses site orang, admin lihat semua)
- [x] Monitoring, alerting, metrics, dashboard (dashboard selesai: `core/monitor.py` `dashboard(conn, owner_id)` — counts sites/dbs/ftp/users (admin semua, client punya sendiri), total_size via `_folder_size`, per-site size + ssl_expiry via openssl `CCPANEL_LETSENCRYPT_LIVE`, `GET /api/dashboard`, DashboardView + route `/` (default redirect login) + nav, badge SSL kadaluarsa/warn <14 hari; E2E: admin lihat 3 site, client cuma site sendiri. **Alerting/metrics deferred** — butuh channel notif (email/webhook) + time-series storage, tanpa spek)
- [x] Apache, OpenLiteSpeed (selesai: `core/webserver.py` dispatcher + `core/apache.py` + `core/litespeed.py` — interface identik nginx: create/activate/enable/disable/remove/trash/restore/purge/vhost_path/root_path/test/reload. Engine global via `CCPANEL_WEBSERVER` env + DB settings `settings.webserver` + `POST /api/settings/webserver` admin-only. Per-site engine disimpan kolom `webserver` di tabel `sites` — operasi per-site dispatch ke engine yang benar. WAF/SSL tetap nginx-only (400 kalau site non-nginx). Fake binaries: `apachectl`, `lshttpd` via PATH. E2E: switch engine → create site → disable/enable → delete → trash → restore → backup/restore semua jalan)
- [x] PostgreSQL, MongoDB, Redis (selesai: `core/database.py` dispatcher + `core/postgresql.py` — interface identik mysql: create_db/reset_password/drop_db/test. Engine default settings `settings.database` + `POST /api/settings/database` admin-only. Kolom `db_type` di tabel `dbs` — operasi dispatch ke database yang benar. MongoDB dan Redis dibuat stub class (`MongoStub`, `RedisStub`) yang melempar `DatabaseError` secara spesifik. DatabaseView tabel + modal diupdate untuk memilih tipe DB. E2E: switch default DB -> create postgresql DB -> reset password -> delete DB postgresql -> create mongodb DB ditolak stub error -> semua berjalan sukses)
- [x] PHP: php-fpm per-site, multi-PHP version (selesai: `core/php.py` — pool config per-site per versi (`CCPANEL_PHP_FPM_DIR`, default `/etc/php`), versi `static/php8.1/php8.2/php8.3`, validasi versi, kolom `php_version` di tabel `sites` + migrasi ALTER, `PUT /api/sites/{id}/php` admin+client (client cuma site sendiri via `_check_site_access`), nginx-only (400 untuk site apache/litespeed, konsisten dgn WAF), sisip/hapus block fastcgi `# BEGIN CCPANEL PHP` di vhost + `nginx -t` + rollback, hapus pool saat switch versi/static/delete site, fake binaries `php-fpm8.x` via PATH, test_php.py 3 tes, E2E browser: dropdown PHP di SitesView switch 8.1↔static + vhost/pool bersih)
- [x] Node.js web frontend (client), Go CLI tool, Docker containerisasi (selesai: `cli/ccpanel/` Go CLI stdlib-only — login/sites CRUD+enable/disable+php/dbs CRUD/backups/dashboard/logs, token simpan `~/.ccpanel.json` 0600, env `CCPANEL_API`/`CCPANEL_TOKEN`/`CCPANEL_CONFIG`, `go build`, `main_test.go` 3 tes; `client/ccpanel.mjs` Node.js client stdlib fetch mirror CLI; `Dockerfile` multi-stage (node build frontend → ubuntu 24.04 + nginx/mariadb/php8.1-8.3/supervisord) + `docker/supervisord.conf` + `docker-compose.yml` + `.dockerignore`. **Docker tak bisa dites lokal** — docker tidak terinstall di lingkungan dev, file disiapkan utk VPS. E2E: Go CLI + Node client create site → php → delete semua jalan lawan server live)
- [x] Start/Stop/Restart service ccpanel (selesai: `scripts/ccpanel-ctl` — start/stop/restart/status, uvicorn background + pidfile `data/ccpanel.pid` + log `data/ccpanel.log`, health check login palsu (401 = hidup, 000 = belum siap), graceful stop + force kill, env override `CCPANEL_PIDFILE`/`CCPANEL_LOGFILE`/`CCPANEL_HOST`/`CCPANEL_PORT`; `scripts/ccpanel.service` systemd unit (EnvironmentFile `/etc/ccpanel.env` opsional); E2E: start → status RUNNING → restart (pid ganti) → stop → status STOPPED semua jalan)
- [ ] Multi-server cluster, HA, CDN (abaikan dulu, butuh load balancer + shared storage + DB cluster)
- [ ] Billing, domain registrar API, marketplace plugin (nanti tinggalkan)

## Keamanan (selalu cek, bukan sekali)
- [x] Semua input divalidasi regex whitelist (domain, db_name, db_user, host/IP)
- [x] Subprocess pakai argumen list, TANPA `shell=True`
- [x] `nginx -t` sebelum reload, rollback kalau gagal
- [x] Default bind `127.0.0.1` — tidak expose ke internet tanpa HTTPS + password kuat
- [x] Path traversal guard aktif di file manager (`resolve()` + prefix check)
- [x] Password DB dari `secrets`/user-defined, disimpan di tabel `dbs` (hanya admin panel akses)


## Yang diinginkan
- [x] Menjalankan apkilasi Node.js diserver ( Node / PM2 / PM2 + systemd unit per-site, endpoint `POST /api/sites/{id}/nodejs` untuk start/stop/restart/status, log tail di FileManagerView)
- [x] Form deploy Node ala aaPanel (selesai: `AppManager.vue` — tabs "Default Project" vs "PM2 Project", field Path/entry, Nama project, Run opt (startup command), Port, User (default www), Versi Node (v22/v20/v18/v16 dari `GET /api/node/versions`, deteksi nvm dir), Remark, Subpath proxy; backend `core/apps.py` `_cmdline`/`_write_unit`/`create_app` dukung `user` (User= di unit), `run_opt`, `pm2` (`pm2 start <entry> --name <name> -- <run_opt>`), `node_version` (export PATH nvm); `api/apps.py` `AppCreate`/`AppResponse` + `create/update` + kolom baru `site_apps` name/run_opt/user/node_version/pm2/remark (migration deps.py); E2E: pasang PM2 app via UI → unit `pm2 start app.js --name freshapp -- npm run prod` + User=appuser + DB field lengkap, update ke default mode → `export PATH=$HOME/.nvm/versions/node/v22/bin:$PATH && /usr/bin/env node server.js --port 3001`, 18 pytest lulus)
- [x] Menjalankan aplikasi Python (Flask/FastAPI) diserver (Gunicorn + systemd unit per-site, endpoint `POST /api/sites/{id}/python` untuk start/stop/restart/status, log tail di FileManagerView)
- [x] Menjalankan aplikasi Go diserver (Go binary + systemd unit per-site, endpoint `POST /api/sites/{id}/go` untuk start/stop/restart/status, log tail di FileManagerView)
- [x] Menjalankan aplikasi Docker diserver (Docker Compose per-site, endpoint `POST /api/sites/{id}/docker` untuk start/stop/restart/status, log tail di FileManagerView)
- [x] Project standalone node/go/python/docker TANPA domain (selesai: halaman baru **Projects** ala aaPanel — tab node/python/go/docker, tabel Nama/Status/PID/Port/Root/Domain/Node/Remark/Aksi, Start/Stop/Restart/Log/Ubah/Hapus; backend tabel `projects` (name unik, app_type, port, entry, root_path, run_opt, user, node_version, pm2, remark, domain, owner_id), unit systemd `ccpanel-proj-<name>.service` di `PROJECT_ROOT/<name>` (`CCPANEL_PROJECT_ROOT` env, default `/www/project`), folder dibuat otomatis, PID dari `systemctl show MainPID`, log via `journalctl -u ccpanel-proj-<name>`; domain opsional: saat create langsung atau `POST /api/projects/{id}/domain` → vhost proxy nginx `proj-<domain>.conf` (listen 80, `location / proxy_pass` ke localhost:port, tanpa root/docroot), detach `DELETE /api/projects/{id}/domain` idempotent, cek bentrok vs site/alias/project lain; api `api/projects.py` CRUD + action + log; `core/apps.py` `create_standalone`/`standalone_action`/`standalone_status`/`project_pid`/`standalone_log_tail`/`remove_standalone`, `core/nginx.py` `project_proxy_enable`/`project_proxy_disable`/`project_vhost_path`; frontend `ProjectsView.vue` + nav "Projects" + route `/projects`; E2E: create tanpa domain (unit + folder), create + domain langsung (vhost + unit), attach/detach domain, update port, action, log (unit benar `ccpanel-proj-<name>`), delete (unit hilang, folder project tetap); 10 pytest baru `test_projects.py` lulus, total 28 lulus)
- [x] App Store runtime + aplikasi pendukung (selesai: halaman baru **App Store** ala aaPanel — tab PHP/Node.js/Go/Aplikasi, tabel Nama/Deskripsi/Status/Aksi, tombol Install/Uninstall, badge Terinstall/Belum; backend `core/appstore.py` katalog `CATALOG` (php7.4-8.3 via apt, node18/20/22/24 via nvm, go1.22/1.23/1.24 SDK, app: nginx/mariadb/redis/postgresql/composer/pm2/certbot/git), deteksi status via `_php_detect`/`_node_detect`/`_go_detect`/`_which`, install/uninstall subprocess argumen-list, log ke `CCPANEL_APPSTORE_LOG`; env override `CCPANEL_APT`/`CCPANEL_NVM_DIR`/`CCPANEL_GO_ROOT`/`CCPANEL_APPSTORE_LOG`; api `api/appstore.py` `GET /api/appstore` + `POST /api/appstore/{id}/install|uninstall`; frontend `AppStoreView.vue` + nav "App Store" + route `/appstore`; 8 pytest baru `test_appstore.py` lulus)
- [x] Proxy project Node.js/Flask/FastAPI/Go/Docker ke subpath domain (misal `example.com/app1` → `http://127.0.0.1:8888/app1`)
- [x] Tabs proyek ala aaPanel (Static/PHP/Node/Python/Go/Docker): site punya kolom `project_type`, list site difilter per tab, buat site pilih tipe
- [x] Multi-domain per site: tabel `site_domains` + endpoint `POST/DELETE /api/sites/{id}/domains` (update `server_name` vhost + rollback), domain utama tidak bisa dihapus
- [x] Form Buat Site ala aaPanel (selesai: `SiteModal.vue` — domain textarea multi-line (baris pertama = domain utama, sisanya = alias), apply SSL (certbot multi-domain `-d domain -d www`), deskripsi, kategori (Blog/Toko/Company/Portofolio/Landing/Lainnya), versi PHP (dropdown muncul saat type php, auto-reset saat ganti type), buat FTP opsional, buat DB MySQL opsional (nama/user/pass auto-fallback dari domain); backend `SiteCreate` + `POST /api/sites` — validasi semua, insert alias ke `site_domains`, create pool php-fpm + fastcgi block saat php, FTP + DB account, SSL certbot, rollback penuh urut terbalik (hapus site/FTP/DB/pool/vhost kalau gagal di tengah); kolom baru `sites.description` + `sites.category` (migration di deps.py); `GET /api/php/versions`; tabel SitesView + kolom Deskripsi + Kategori; E2E: create php multi-domain + deskripsi + kategori + FTP + DB + SSL via UI semua jalan, rollback DB bentrok bersih, 18 pytest lulus)
- [x] Proxy project domain penuh: site punya kolom `port` + `proxy_enabled`, toggle `POST /api/sites/{id}/proxy` — nginx listen di port + `location / proxy_pass` ke app localhost, ubah port saat proxy ON diterapkan langsung, balik static via proxy OFF
- [x] Edit Config vhost (nginx/apache/litespeed) via panel (tombol "Edit Config" di SitesView, textarea + syntax highlight, simpan → `nginx -t` → reload) per-site, rollback kalau gagal
- [x] File manager lanjutan (selesai: `POST /files/mkdir` buat folder, `POST /files/rename` rename (nama divalidasi, tolak `../`), `GET/PUT /files/content` edit file teks (batas 2MB + deteksi binary via null-byte/rasio byte), `POST /files/extract` unzip/untar.gz/tgz/tbz2/txz (zip-slip guard — entry yang resolve keluar folder tujuan ditolak, symlink tar dilewati), `POST /files/chmod` (mode oktal 3-4 digit), `POST /files/chown` (user/user:group/:group, nama atau numeric ID), `GET /files/download` (file langsung FileResponse, folder → zip streaming BytesIO); frontend FileManager: toolbar + Folder, tombol Edit/Extract/Rename/chmod/chown/Download per baris, modal editor teks; download pakai fetch blob + Bearer token (anchor `<a>` biasa 401); E2E: mkdir→upload→edit→rename→extract zip+tar→zip-slip ditolak→chmod 600→chown 1000:1000→download zip semua jalan)
- [x] File manager jadi halaman full (selesai: `FileManagerView.vue` route `/files/:siteId?` + nav sidebar "Files", bukan modal lagi — breadcrumb klik navigasi, select pindah site, editor teks inline full-width (min-height 60vh) menggantikan overlay, format ukuran B/KB/MB; tombol Files di SitesView → `router.push` ke route; `FileManager.vue` modal dihapus; E2E: `/files` redirect ke site pertama, edit-simpan, breadcrumb root, navigasi dari SitesView semua jalan)