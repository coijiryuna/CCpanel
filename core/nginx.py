"""Operasi nginx: vhost template, buat/hapus site, enable/disable.

Semua path bisa dioverride via env var supaya bisa diuji tanpa root.
Argumen subprocess selalu list — tanpa shell=True.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import validate

NGINX_CONF_DIR = Path(os.environ.get("CCPANEL_NGINX_CONF_DIR", "/etc/nginx/conf.d"))
WWW_ROOT = Path(os.environ.get("CCPANEL_WWW_ROOT", "/www/wwwroot"))
TRASH_DIR = Path(os.environ.get("CCPANEL_TRASH_DIR", "/www/trash"))
SYSTEMCTL = os.environ.get("CCPANEL_SYSTEMCTL", "systemctl")

VHOST_TEMPLATE = """server {{
    listen 80;
    listen [::]:80;

    server_name {server_name};

    index index.php index.html index.htm default.php default.htm default.html;

    root {root};

    #Subdirectory-configuration-start
    include /www/server/panel/vhost/nginx/sub_dir/{domain}/*.conf;
    #Subdirectory-configuration-end

    include /www/server/panel/vhost/nginx/extension/{domain}/*.conf;

    #SSL-START SSL related configuration, do NOT delete or modify the next line of commented-out 404 rules
    #error_page 404/404.html;
    #SSL-END

    #ERROR-PAGE-START  Error page configuration, allowed to be commented, deleted or modified
    error_page 404 /404.html;
    error_page 502 /502.html;
    #ERROR-PAGE-END

    #PHP-INFO-START PHP reference configuration, allowed to be commented, deleted or modified
    include enable-php-00.conf;
    #PHP-INFO-END

    #REWRITE-START URL rewrite rule reference, any modification will invalidate the rewrite rules set by the panel
    include /www/server/panel/vhost/rewrite/{domain}.conf;
    #REWRITE-END

    # Forbidden files or directories
    location ~ ^/(\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md) {{
        return 404;
    }}

    # Directory verification related settings for one-click application for SSL certificate
    location ~ \\.well-known {{
        allow all;
    }}

    # Prohibit putting sensitive files in certificate verification directory
    if ( $uri ~ "^/\\.well-known/.*\\.(php|jsp|py|js|css|lua|ts|go|zip|tar\\.gz|rar|7z|sql|bak)$" ) {{
        return 403;
    }}

    access_log /www/wwwlogs/{domain}.log;
    error_log  /www/wwwlogs/{domain}.error.log;
}}
"""

DEFAULT_INDEX = """<!doctype html>
<html lang="id">
<head><meta charset="utf-8"><title>{domain}</title></head>
<body><h1>It works!</h1><p>Website <code>{domain}</code> aktif.</p></body>
</html>
"""


class NginxError(Exception):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def vhost_path(domain: str) -> Path:
    return NGINX_CONF_DIR / f"{domain}.conf"


def root_path(domain: str) -> Path:
    return WWW_ROOT / domain


def nginx_test() -> None:
    """Validasi konfigurasi. Raise NginxError kalau gagal."""
    res = _run(["nginx", "-t"])
    if res.returncode != 0:
        raise NginxError(res.stderr.strip() or res.stdout.strip() or "nginx -t failed")


def nginx_reload() -> None:
    # skip reload kalau service tak aktif (mis. apache diinstall tapi belum start)
    if _run([SYSTEMCTL, "is-active", "--quiet", "nginx"]).returncode != 0:
        return
    res = _run([SYSTEMCTL, "reload", "nginx"])
    if res.returncode != 0:
        raise NginxError(res.stderr.strip() or "systemctl reload nginx failed")


def _write_vhost(domain: str, root: Path, server_names: list[str] | None = None,
                 port: int = 0, running_dir: str = "") -> None:
    """Tulis vhost. server_names: list domain (utama + tambahan), default [domain].
    port > 0: server listen di port itu (bukan 80) — dipakai proxy project
    (app jalan di localhost:<port>, nginx forward dari port itu).
    running_dir: subdirectory untuk document root (e.g., public, public_html, ThinkPHP5, Laravel, Codeigniter)
    """
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    names = [d for d in (server_names or [domain]) if d]
    if domain not in names:
        names.insert(0, domain)
    listen = f"listen {port};\n    listen [::]:{port};" if port else "listen 80;\n    listen [::]:80;"
    # Use running_dir if provided, otherwise use root
    doc_root = str(root / running_dir) if running_dir else str(root)
    conf = VHOST_TEMPLATE.format(server_name=" ".join(names), root=doc_root, domain=domain)
    conf = conf.replace("listen 80;\n    listen [::]:80;", listen, 1)
    vhost_path(domain).write_text(conf)


def create_site(domain: str, running_dir: str = "") -> Path:
    """Buat folder root + index default + vhost. Rollback penuh kalau nginx -t gagal.

    Folder root yang SUDAH ADA tidak pernah di-rmtree — cegah hapus data user
    (site mungkin dibuat manual sebelum pakai panel).
    """
    root = root_path(domain)
    if root.exists():
        raise NginxError(f"Folder root sudah ada: {root}")
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # race: folder muncul antara cek dan mkdir — jangan sentuh isinya
        raise NginxError(f"Folder root sudah ada: {root}") from None
    try:
        (root / "index.html").write_text(DEFAULT_INDEX.format(domain=domain))
        _write_vhost(domain, root, running_dir=running_dir)
        nginx_test()
    except Exception as e:
        # rollback: bersihkan config + folder (folder pasti buatan kita di sini)
        vhost_path(domain).unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)
        if isinstance(e, NginxError):
            raise
        raise NginxError(f"create_site failed: {e}") from e
    nginx_reload()
    return root


def activate_site(domain: str, running_dir: str = "") -> None:
    """Tulis vhost untuk folder root yang SUDAH ADA (restore backup).

    Tidak membuat folder, tidak menyentuh isinya. nginx -t dulu, rollback
    hapus vhost kalau gagal.
    running_dir: subdirectory untuk document root (e.g., public, public_html, ThinkPHP5, Laravel, Codeigniter)
    """
    root = root_path(domain)
    if not root.is_dir():
        raise NginxError(f"Folder root tidak ada: {root}")
    if vhost_path(domain).exists():
        raise NginxError(f"vhost {vhost_path(domain)} sudah ada")
    _write_vhost(domain, root, running_dir=running_dir)
    try:
        nginx_test()
    except NginxError:
        vhost_path(domain).unlink(missing_ok=True)
        raise
    nginx_reload()


def _proxy_block(subpath: str, port: int) -> str:
    return (
        f"    location {subpath} {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }"
    )


def _proxy_re(subpath: str) -> re.Pattern:
    return re.compile(
        rf"\n[ \t]*location {re.escape(subpath)} \{{.*?\n[ \t]*\}}\n", re.DOTALL
    )


def proxy_insert(domain: str, subpath: str, port: int) -> None:
    """Sisipkan location block proxy ke vhost untuk subpath.

    Replace kalau subpath sudah ada (ganti port). Backup dulu; rollback
    kalau nginx -t gagal.
    """
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    conf = vh.read_text()
    backup = conf
    block = "\n" + _proxy_block(subpath, port) + "\n"
    if _proxy_re(subpath).search(conf):
        conf = _proxy_re(subpath).sub(block, conf, count=1)
    else:
        idx = conf.rstrip().rfind("}")
        if idx == -1:
            raise NginxError(f"vhost {vh} tidak valid (tanpa penutup)")
        conf = conf[:idx] + block + conf[idx:]
    vh.write_text(conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(backup)
        raise
    nginx_reload()


def proxy_remove(domain: str, subpath: str) -> None:
    """Hapus location block subpath dari vhost. Tidak ada = anggap sukses."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    conf = vh.read_text()
    new_conf = _proxy_re(subpath).sub("\n", conf, count=1)
    if new_conf == conf:
        return
    vh.write_text(new_conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(conf)
        raise
    nginx_reload()

# ------------------------------------------------- proxy penuh (domain → port)

def _root_location_span(conf: str) -> tuple[int, int] | None:
    """Span (start, end) block `location / { ... }` — brace counting biar
    tahan nested block (fastcgi, proxy subpath). None kalau tidak ada."""
    m = re.search(r"\n[ \t]*location / \{", conf)
    if not m:
        return None
    start = m.start()
    # regex sudah termasuk `{` — scan body mulai dari akhir match
    depth = 1
    i = m.end()
    while i < len(conf) and depth:
        if conf[i] == "{":
            depth += 1
        elif conf[i] == "}":
            depth -= 1
        i += 1
    if depth:
        raise NginxError("vhost tidak valid (brace tidak seimbang)")
    return start, i

def _proxy_root_block(port: int) -> str:
    return (
        f"    location / {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }"
    )

def _static_root_block() -> str:
    return "    location / {\n        try_files $uri $uri/ =404;\n    }"

def _set_listen(conf: str, port: int) -> str:
    """Ganti `listen <n>;` pertama jadi `listen <port>;` (default 80)."""
    if re.search(rf"\n[ \t]*listen\s+{port};", conf):
        return conf
    m = re.search(r"\n[ \t]*listen\s+\d+;", conf)
    if not m:
        raise NginxError("vhost tidak punya direktif listen")
    return conf[:m.start()] + f"\n    listen {port};" + conf[m.end():]

def _set_root_location(conf: str, port: int, proxy: bool) -> str:
    new_block = _proxy_root_block(port) if proxy else _static_root_block()
    span = _root_location_span(conf)
    if span:
        start, end = span
        return conf[:start] + "\n" + new_block + "\n" + conf[end:]
    # tidak ada location / — sisip sebelum penutup server block
    idx = conf.rstrip().rfind("}")
    if idx == -1:
        raise NginxError("vhost tidak valid (tanpa penutup)")
    return conf[:idx] + "\n" + new_block + "\n" + conf[idx:]

def proxy_enable(domain: str, port: int) -> None:
    """Mode proxy penuh: vhost listen di port + location / proxy_pass ke app.
    Dipakai proxy project domain penuh (app di localhost:<port>)."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    conf = vh.read_text()
    backup = conf
    try:
        conf = _set_listen(conf, port)
        conf = _set_root_location(conf, port, proxy=True)
    except NginxError:
        raise
    vh.write_text(conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(backup)
        raise
    nginx_reload()

def proxy_disable(domain: str) -> None:
    """Balik ke static: listen 80 + location / try_files."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    conf = vh.read_text()
    backup = conf
    try:
        conf = _set_listen(conf, 80)
        conf = _set_root_location(conf, 0, proxy=False)
    except NginxError:
        raise
    vh.write_text(conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(backup)
        raise
    nginx_reload()

# -------------------------------------------- front proxy multi-web-server
# Arsitektur aaPanel: nginx front pegang 80/443, apache/OpenLiteSpeed backend
# di port khusus (8288/8188). Site backend dapat nginx vhost di 80 yang
# proxy_pass ke 127.0.0.1:<port-backend>. listen SELALU 80 (front).

_SSL_DIRECTIVE_RE = re.compile(
    r"\n[ \t]*(listen\s+443[^;]*;|ssl_certificate[^;]*;|ssl_certificate_key[^;]*;"
    r"|ssl_trusted_certificate[^;]*;|ssl_dhparam[^;]*;|ssl_session_cache[^;]*;"
    r"|ssl_session_timeout[^;]*;|ssl_protocols[^;]*;|ssl_ciphers[^;]*;"
    r"|ssl_prefer_server_ciphers[^;]*;|ssl_stapling[^;]*;|ssl_stapling_verify[^;]*;)"
)

def _front_proxy_conf(domain: str, port: int, ssl: str = "") -> str:
    """conf front proxy (aaPanel style). `ssl` = direktif SSL dari vhost lama (preserve
    supaya TLS termination tetap jalan saat vhost front ditimpa ulang)."""
    return (
        "server {\n"
        "    listen 80;\n"
        "    listen [::]:80;\n"
        f"{ssl}"
        f"    server_name {domain};\n"
        "\n"
        "    index index.php index.html index.htm default.php default.htm default.html;\n"
        f"    root /www/wwwroot/{domain}/;\n"
        "\n"
        "    #Subdirectory-configuration-start\n"
        f"    #include /www/server/panel/vhost/nginx/sub_dir/{domain}/*.conf;\n"
        "    #Subdirectory-configuration-end\n"
        "\n"
        f"    include /www/server/panel/vhost/nginx/extension/{domain}/*.conf;\n"
        "\n"
        "    #PHP-INFO-START  PHP reference configuration, allowed to be commented, deleted or modified\n"
        "    #include enable-php-00.conf;\n"
        "    #PHP-INFO-END\n"
        "\n"
        "    #SSL-START SSL related configuration, do NOT delete or modify the next line of commented-out 404 rules\n"
        "    #error_page 404/404.html;\n"
        "    #SSL-END\n"
        "\n"
        "    #REWRITE-START URL rewrite rule reference, any modification will invalidate the rewrite rules set by the panel\n"
        f"    # include /www/server/panel/vhost/rewrite/{domain}.conf;\n"
        "    #REWRITE-END\n"
        "\n"
        "    #ERROR-PAGE-START  Error page configuration, allowed to be commented, deleted or modified\n"
        "    #error_page 404 /404.html;\n"
        "    #error_page 502 /502.html;\n"
        "    #ERROR-PAGE-END\n"
        "\n"
        f"    location / {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_set_header REMOTE-HOST $remote_addr;\n"
        "        proxy_set_header SERVER_PROTOCOL $server_protocol;\n"
        "        proxy_set_header HTTPS $https;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        "        proxy_set_header Connection \"upgrade\";\n"
        "        proxy_set_header REMOTE_ADDR $remote_addr;\n"
        "        proxy_set_header REMOTE_PORT $remote_port;\n"
        "        add_header Cache-Control no-cache;\n"
        "    }\n"
        "\n"
        "    # Forbidden files or directories\n"
        "    location ~ ^/(\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md) {\n"
        "        return 404;\n"
        "    }\n"
        "\n"
        "    location ~ \\.well-known {\n"
        "        allow all;\n"
        f"        root /www/wwwroot/{domain}/;\n"
        "        try_files $uri =404;\n"
        "    }\n"
        "\n"
        "    # Prohibit putting sensitive files in certificate verification directory\n"
        "    if ( $uri ~ \"^/\\.well-known/.*\\.(php|jsp|py|js|css|lua|ts|go|zip|tar\\.gz|rar|7z|sql|bak)$\" ) {\n"
        "        return 403;\n"
        "    }\n"
        "\n"
        f"    access_log /www/wwwlogs/{domain}.log;\n"
        f"    error_log  /www/wwwlogs/{domain}.error.log;\n"
        "\n"
        "}\n"
    )

def _extract_ssl_directives(conf: str) -> str:
    """Ambil semua direktif SSL (listen 443 + ssl_*) dari conf, dipisah newline."""
    return "".join(m.group(0) + "\n" for m in _SSL_DIRECTIVE_RE.finditer(conf))

def front_proxy_enable(domain: str, port: int) -> None:
    """Multi mode: tulis/replace nginx vhost front proxy -> backend port.
    Direktif SSL (443 + ssl_*) dari vhost lama di-PRESERVE — site tetap HTTPS
    setelah switch engine / recreate front. nginx -t dulu; rollback backup kalau gagal."""
    if not validate.valid_domain(domain):
        raise NginxError(f"Domain tidak valid: {domain}")
    vh = vhost_path(domain)
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    backup = vh.read_text() if vh.exists() else None
    ssl = _extract_ssl_directives(backup) if backup else ""
    vh.write_text(_front_proxy_conf(domain, port, ssl))
    try:
        nginx_test()
    except NginxError:
        if backup is not None:
            vh.write_text(backup)
        else:
            vh.unlink(missing_ok=True)
        raise
    nginx_reload()

def front_proxy_disable(domain: str) -> None:
    """Multi mode: balik nginx vhost front ke static (site dilayani nginx)."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    conf = vh.read_text()
    backup = conf
    try:
        conf = _set_root_location(conf, 0, proxy=False)
    except NginxError:
        raise
    vh.write_text(conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(backup)
        raise
    nginx_reload()

# --------------------------------------------- vhost project standalone (domain)

def project_vhost_path(domain: str) -> Path:
    return NGINX_CONF_DIR / f"proj-{domain}.conf"

def _project_proxy_conf(domain: str, port: int) -> str:
    return (
        f"server {{\n"
        f"    listen 80;\n"
        f"    server_name {domain};\n"
        "\n"
        f"    location / {{\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "    }\n"
        "}\n"
    )

def project_proxy_enable(domain: str, port: int) -> None:
    """Pasang vhost proxy penuh project standalone: domain → localhost:port.
    Tulis `proj-<domain>.conf` baru (root tidak disentuh — project tidak punya
    docroot). nginx -t dulu; rollback hapus file kalau gagal."""
    if not validate.valid_domain(domain):
        raise NginxError(f"Domain tidak valid: {domain}")
    vh = project_vhost_path(domain)
    if vh.exists():
        raise NginxError(f"Vhost project sudah ada: {vh}")
    NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
    vh.write_text(_project_proxy_conf(domain, port))
    try:
        nginx_test()
    except NginxError:
        vh.unlink(missing_ok=True)
        raise
    nginx_reload()

def project_proxy_disable(domain: str) -> None:
    """Hapus vhost proxy project. Tidak ada = anggap sukses (idempotent)."""
    vh = project_vhost_path(domain)
    if not vh.exists():
        return
    vh.unlink()
    try:
        nginx_test()
    except NginxError:
        # rollback: tulis ulang biar config konsisten lagi
        NGINX_CONF_DIR.mkdir(parents=True, exist_ok=True)
        vh.write_text(_project_proxy_conf(domain, 1))
        raise
    nginx_reload()

# ----------------------------------------------------- domain tambahan (alias)

def set_server_names(domain: str, names: list[str]) -> None:
    """Update server_name vhost (domain utama + tambahan). Main selalu pertama."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise NginxError(f"vhost {vh} tidak ada")
    names = [n for n in names if n]
    if domain in names:
        names.remove(domain)
    names.insert(0, domain)
    conf = vh.read_text()
    backup = conf
    if not re.search(r"server_name\s+[^;]+;", conf):
        raise NginxError("vhost tidak punya direktif server_name")
    conf = re.sub(r"server_name\s+[^;]+;", f"server_name {' '.join(names)};", conf, count=1)
    vh.write_text(conf)
    try:
        nginx_test()
    except NginxError:
        vh.write_text(backup)
        raise
    nginx_reload()


def set_enabled(domain: str, enabled: bool) -> None:
    vh = vhost_path(domain)
    disabled = vh.with_name(vh.name + ".disabled")
    if enabled:
        if not disabled.exists():
            raise NginxError(f"vhost {vh} tidak ada")
        disabled.rename(vh)
    else:
        if not vh.exists():
            raise NginxError(f"vhost {vh} tidak ada")
        vh.rename(disabled)
    try:
        nginx_test()
    except NginxError:
        # rollback rename
        if enabled:
            vh.rename(disabled)
        else:
            disabled.rename(vh)
        raise
    nginx_reload()

def remove_vhost(domain: str) -> None:
    """Hapus vhost saja — root TETAP. Untuk switch engine antar server.
    Tidak menyentuh folder root (beda dari remove_site yang trash)."""
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        nginx_test()
    except NginxError:
        if backup is not None:
            vh.write_text(backup)
        raise
    nginx_reload()


def remove_site(domain: str) -> None:
    """Hapus vhost, lalu pindah folder root ke trash — BUKAN rm -rf.

    Backup vhost dulu; kalau nginx -t gagal setelah unlink, restore vhost
    supaya site tidak mati karena error config lain.
    """
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        nginx_test()
    except NginxError:
        if backup is not None:
            vh.write_text(backup)
        raise
    nginx_reload()

    root = root_path(domain)
    if root.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        dest = TRASH_DIR / domain
        # kalau trash sudah ada isinya, tambah suffix timestamp
        if dest.exists():
            import time

            dest = TRASH_DIR / f"{domain}.{int(time.time())}"
        shutil.move(str(root), str(dest))


def trash_items() -> list[dict]:
    """Daftar folder di trash: {name, size, mtime}. Kosong kalau trash tak ada."""
    if not TRASH_DIR.is_dir():
        return []
    items = []
    for p in sorted(TRASH_DIR.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir():
            continue
        size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        items.append({"name": p.name, "size": size, "mtime": p.stat().st_mtime})
    return items


def restore_site(trash_name: str) -> str:
    """Pindah folder trash balik ke WWW_ROOT/<domain> + tulis vhost + reload.

    Domain diambil dari nama folder trash (kalau ada suffix .timestamp, domain
    = bagian sebelum .<10-digit>). Return domain yang direstore.
    """
    src = TRASH_DIR / trash_name
    if not src.is_dir():
        raise NginxError(f"Trash item tidak ada: {trash_name}")
    # name = "domain" atau "domain.<10-digit-timestamp>" (suffix saat trash sudah isi)
    m = re.match(r"^(.*)\.(\d{10})$", trash_name)
    domain = m.group(1) if m else trash_name
    if not validate.valid_domain(domain):
        raise NginxError(f"Nama trash tidak valid: {trash_name}")

    root = root_path(domain)
    if root.exists():
        raise NginxError(f"Folder root sudah ada: {root} — restore dibatalkan")

    vh = vhost_path(domain)
    if vh.exists():
        raise NginxError(f"vhost {vh} sudah ada — restore dibatalkan")

    try:
        shutil.move(str(src), str(root))
        _write_vhost(domain, root)
        nginx_test()
    except Exception as e:
        # rollback: kembalikan folder ke trash, hapus vhost kalau sempat dibuat
        vh.unlink(missing_ok=True)
        if root.exists() and not src.exists():
            shutil.move(str(root), str(src))
        if isinstance(e, NginxError):
            raise
        raise NginxError(f"restore_site failed: {e}") from e
    nginx_reload()
    return domain


def purge_site(trash_name: str) -> None:
    """Hapus permanen folder trash. Nama divalidasi dulu — hanya isi TRASH_DIR."""
    if "/" in trash_name or "\\" in trash_name or trash_name in ("", ".", ".."):
        raise NginxError(f"Nama trash tidak valid: {trash_name}")
    target = (TRASH_DIR / trash_name).resolve()
    if TRASH_DIR.resolve() not in target.parents:
        raise NginxError(f"Nama trash tidak valid: {trash_name}")
    if not target.exists():
        raise NginxError(f"Trash item tidak ada: {trash_name}")
    shutil.rmtree(target)
