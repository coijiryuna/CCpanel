# CCPanel project notes

## Stack
- Backend: Python FastAPI (server.py), SQLite (data/ccpanel.db), JWT auth (pyjwt), bcrypt
- DASHBOARD: Vue 3 + TS strict di dashboard/, build ke ../static. `npm run build` = vue-tsc --build + vite.
- MySQL ops via CLI subprocess (core/mysql.py), root socket auth. nginx ops di core/nginx.py.

## Struktur penting
- core/validate.py: DOMAIN_RE (harus ada titik), DB_NAME_RE
- Path traversal guard: _resolve_within() di server.py
- DELETE site = trash, bukan rm -rf. create_site: root existing → tolak, JANGAN rmtree
- PENTING: mount StaticFiles("/") PALING AKHIR di server.py (POST/PUT/DELETE kena 405 kalau di atas)
- Upload: tolak raw != basename (cegah ../ traversal via filename)

## Test
- `.venv/bin/python -m pytest -q` — 74 pass (per 2026-08-09)
- conftest.py: semua CCPANEL_* env ke /tmp shared, mock nginx/apachectl/lshttpd/php-fpm/systemctl/echo + PATH
- TestClient butuh httpx. DB di-reset antara test (state lama bikin key error)

## Dashboard TS
- Type-check WAJIB `npx vue-tsc --build` — `--noEmit` baca root tsconfig (files:[]) → false-0 error.
- Pola anti-error TS strict: `ref<T[]>([])`, `api.get<T>(...)`, catch `(e: unknown)`, modal `ref<T|null>(null)` + guard, :disabled → Booleanish.
- api service `dashboard/src/services/api.ts`: get/post/put/delete generic, punya `blob()`.
- useSidebar butuh SidebarProvider (dibungkus di DashboardLayout.vue).

## Run (dev)
- `./run-dev.sh` → uvicorn 127.0.0.1:8888 --reload, PANEL_PASSWORD=test123, CCPANEL_DATA_DIR=/tmp/ccp-demo
- Login: username admin / password test123. Endpoint login: POST /api/login (username+password)
- run-dev.sh TIDAK set CCPANEL_SYSTEMCTL/DOCKER_BIN — pakai systemctl/docker asli

## Multi-WebServer (nginx/apache/litespeed per site)
- core/webserver.py: dispatcher, ENGINES={nginx,apache,litespeed}, ACTIVE dari CCPANEL_WEBSERVER (default nginx). for_engine(e) → modul. Interface identik: create_site/activate_site/set_enabled/remove_site/nginx_test/nginx_reload/vhost_path/root_path.
- nginx_set_server_names HANYA di nginx.py — caller guard hasattr.
- apache.py: CCPANEL_APACHE_CONF_DIR (default /etc/apache2/sites-available), vhost `<VirtualHost *:80>`. litespeed.py: CCPANEL_LSWS_CONF_DIR, LSWS_BIN, nginx_test=`lshttpd -t`, nginx_reload=`lshttpd restart`, TANPA systemctl.
- PENTING: nginx_reload() (nginx+apache) SKIP reload kalau `systemctl is-active --quiet` gagal (service installed tapi belum start) — konfigurasi sudah divalidasi `-t`. Kalau tidak, create site apache gagal 500 saat apache2 inactive.
- core/php.py: _php_block_for(engine,...) — nginx `location ~ \.php$` fastcgi_pass unix sock; apache/litespeed `<FilesMatch "\.php$"> SetHandler "proxy:unix:{sock}|fcgi://localhost"`. Marker `# BEGIN/END CCPANEL PHP`.
- insert/remove_php_block/set_php_version TERIMA param `engine` eksplisit (dari DB sites.webserver). Fallback _detect_engine(path): "/apache"|"sites-available"→apache, "lsws"|"litespeed"→litespeed, else nginx. JANGAN andalkan deteksi path di prod.
- API create site: SiteCreate.webserver ("" = engine aktif), validasi ∈ ENGINES. PUT /api/sites/{id}/php bebas engine.
- WAF/hotlink/alias/proxy endpoint MASIH nginx-only (guard `row["webserver"] != "nginx"`).
- core/hotlink.py: vhost include {HOTLINK_DIR}/{domain}.conf, file `location ~* \.(exts)$ { valid_referers none blocked server_names; if ($invalid_referer) { return 403; } }` atau `# hotlink off`. Env CCPANEL_HOTLINK_DIR (default /etc/nginx/hotlink.d). INCLUDE_RE: `include\s+\S*hotlink[^/]*/\S*;` (cocok hotlink.d DAN hotlink — jangan hardcode `.d`).
- Dashboard ModalSiteView.vue: dropdown Web Server (Default/nginx/apache/litespeed). WebsiteView.vue: kolom Engine + PHP_VERSIONS=['static','php8.1'..'php8.4'].
- Detail aaPanel (PLAN.md): single engine aktif; port Nginx 80/443, Apache 8288/8290+8289, OLS 8188/8190+7080.

## core/apps.py (project/app runner)
- _run() catch FileNotFoundError → AppError (docker tak terinstall → status jangan 500). standalone_status/app_status docker catch AppError → inactive. Tanpa ini GET /api/projects 500 kalau docker binary tak ada.
- systemctl(*args) pakai CCPANEL_SYSTEMCTL env. APP_TYPES = node/python/go/docker. Docker pakai compose up/down/restart/logs/ps.
- create_project API butuh systemctl asli (unit /tmp tak dikenal) → di dev, seed project via INSERT DB langsung + tulis unit file manual.

## Data sample dev (JANGAN dihapus — user test layout)
- Sites (7): tokopedia.test(static/nginx/Blog), bukalapak.test(php/nginx/Ecommerce), traveloka.test(static/apache/Company Profile), gojek.test(static/nginx/Portofolio), shopee.test(php/nginx/Ecommerce), grab.test(static/nginx/Landing Page), bca.test(php/apache/Other). litespeed site GAGAL di dev (lshttpd tak terinstall) — wajar.
- Projects (4): node-app(3001), py-api(3002), go-svc(3003), docker-web(3004) — semua state inactive (dev tanpa systemd/docker).
