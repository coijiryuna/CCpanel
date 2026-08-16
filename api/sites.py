"""API sites: CRUD website, enable/disable, WAF, PHP version, project type,
multi-domain, proxy penuh."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import hotlink as hotlink_ops
from core import php as php_ops
from core import validate
from core import waf as waf_ops
from core import webserver as webserver_ops

from .deps import _log, app, check_site_access, dt_order, dt_params, dt_response, db_conn, require_auth

PROJECT_TYPES = ["static", "php"]

class SiteCreate(BaseModel):
    domain: str
    project_type: str = "static"
    port: int = 0
    extra_domains: list[str] = []
    apply_ssl: bool = False
    description: str = ""
    category: str = ""
    php_version: str = "static"
    webserver: str = ""          # nginx/apache/litespeed, kosong = engine aktif
    create_ftp: bool = False
    ftp_username: str = ""
    ftp_password: str = ""
    create_db: bool = False
    db_name: str = ""
    db_user: str = ""
    db_pass: str = ""
    site_dir: str = ""           # custom site directory (relative to root_path)
    running_dir: str = ""        # running directory (e.g., public, public_html, ThinkPHP5, Laravel, Codeigniter)

class DomainAdd(BaseModel):
    domain: str

class SiteResponse(BaseModel):
    id: int
    domain: str
    root_path: str
    site_dir: str
    running_dir: str
    vhost_path: str
    enabled: bool
    waf_enabled: bool
    hotlink_enabled: bool
    webserver: str
    php_version: str
    project_type: str
    port: int
    proxy_enabled: bool
    extra_domains: list[str] = []
    description: str = ""
    category: str = ""
    created_at: str
    app: dict | None = None

def _site_row(row, conn=None) -> SiteResponse:
    extra = []
    if conn is not None:
        extra = [
            r["domain"]
            for r in conn.execute("SELECT domain FROM site_domains WHERE site_id = ?", (row["id"],)).fetchall()
        ]
    return SiteResponse(
        id=row["id"],
        domain=row["domain"],
        root_path=row["root_path"],
        site_dir=row["site_dir"] if "site_dir" in row.keys() else "",
        running_dir=row["running_dir"] if "running_dir" in row.keys() else "",
        vhost_path=row["vhost_path"],
        enabled=bool(row["enabled"]),
        waf_enabled=bool(row["waf_enabled"]),
        hotlink_enabled=bool(row["hotlink_enabled"]) if "hotlink_enabled" in row.keys() else False,
        webserver=row["webserver"] if "webserver" in row.keys() else "nginx",
        php_version=row["php_version"] if "php_version" in row.keys() else "static",
        project_type=row["project_type"] if "project_type" in row.keys() else "static",
        port=row["port"] if "port" in row.keys() else 0,
        proxy_enabled=bool(row["proxy_enabled"]) if "proxy_enabled" in row.keys() else False,
        extra_domains=extra,
        description=row["description"] if "description" in row.keys() else "",
        category=row["category"] if "category" in row.keys() else "",
        created_at=row["created_at"],
    )

@app.delete("/api/sites/{site_id}")
def delete_site(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Hapus vhost + pindah folder ke trash. Bukan hapus permanen."""
    from core import apps as apps_ops
    from core import php as php_ops

    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        eng = webserver_ops.for_engine(row["webserver"])
        try:
            eng.remove_site(row["domain"])
            # multi mode: hapus juga nginx front proxy (site backend punya
            # vhost nginx di 80 yang proxy ke port backend)
            if webserver_ops.is_multi() and row["webserver"] != "nginx":
                webserver_ops.for_engine("nginx").remove_vhost(row["domain"])
            # hapus pool php-fpm + block fastcgi kalau site pakai PHP
            if row["php_version"] != "static":
                php_ops.remove_pool(row["domain"], row["php_version"])
                php_ops.remove_php_block(row["domain"], Path(row["vhost_path"]), row["webserver"])
            # hapus app runner kalau ada (systemd unit / docker compose)
            app = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchone()
            if app is not None:
                apps_ops.remove_app(row["domain"], Path(row["root_path"]), app["app_type"])
        except (webserver_ops.WebserverError, php_ops.PhpError, apps_ops.AppError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
        _log(conn, user, "site.delete", row["domain"])
    return {"ok": True, "trashed": True}

@app.post("/api/sites", response_model=SiteResponse)
def create_site(req: SiteCreate, user: dict = Depends(require_auth)) -> SiteResponse:
    from core import cert as cert_ops
    from core import database as database_ops
    from core import ftp as ftp_ops

    domain = req.domain.strip().lower()
    if not validate.valid_domain(domain):
        raise HTTPException(400, "Domain tidak valid")
    ptype = (req.project_type or "static").lower()
    if ptype not in PROJECT_TYPES:
        raise HTTPException(400, f"Tipe proyek tidak valid. Pilihan: {', '.join(PROJECT_TYPES)}")
    port = req.port or 0
    if port and not 1 <= port <= 65535:
        raise HTTPException(400, "Port tidak valid")
    extra = [d.strip().lower() for d in (req.extra_domains or []) if d and d.strip()]
    for d in extra:
        if not validate.valid_domain(d):
            raise HTTPException(400, f"Domain tambahan tidak valid: {d}")
    if domain in extra:
        extra.remove(domain)
    # php version hanya relevan utk project type php
    php_version = req.php_version or "static"
    if ptype != "php":
        php_version = "static"
    if php_version != "static" and php_version not in php_ops.PHP_VERSIONS:
        raise HTTPException(400, f"PHP version tidak valid. Pilihan: {', '.join(php_ops.PHP_VERSIONS)}")
    description = (req.description or "").strip()
    category = (req.category or "").strip()
    site_dir = (req.site_dir or "").strip()
    running_dir = (req.running_dir or "").strip()
    # engine web server: kosong = engine aktif panel, else validasi
    engine = (req.webserver or "").strip().lower() or webserver_ops.ACTIVE
    if engine not in webserver_ops.ENGINES:
        raise HTTPException(400, f"Web server tidak valid. Pilihan: {', '.join(webserver_ops.ENGINES)}")

    with db_conn() as conn:
        if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, "Domain sudah ada")
        for d in extra:
            if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (d,)).fetchone():
                raise HTTPException(409, f"Domain tambahan sudah dipakai situs lain: {d}")
        eng = webserver_ops.for_engine(engine)
        try:
            root = eng.create_site(domain, running_dir)
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e

        # multi mode: site engine backend (apache/litespeed) butuh nginx front
        # proxy di 80 -> port backend. Rollback front proxy kalau gagal.
        front_done = False
        if webserver_ops.is_multi() and engine != "nginx":
            try:
                webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port(engine))
                front_done = True
            except webserver_ops.WebserverError as e:
                try:
                    eng.remove_vhost(domain)
                except Exception:
                    pass
                raise HTTPException(500, f"Gagal pasang front proxy: {e}") from e

        # FTP + DB harus dibuat SEBELUM insert site (butuh site_id utk FK)
        site_id = None
        ftp_created = None
        db_created = None
        try:
            if extra:
                if engine == "nginx":
                    webserver_ops.nginx_set_server_names(domain, [domain] + extra)
                else:
                    eng.nginx_set_server_names(domain, [domain] + extra) if hasattr(eng, "nginx_set_server_names") else None
            # insert site dulu supaya punya site_id
            cur = conn.execute(
                "INSERT INTO sites (domain, root_path, site_dir, running_dir, vhost_path, enabled, owner_id, webserver, php_version, project_type, port, proxy_enabled, description, category, created_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
                (domain, str(root), site_dir, running_dir, str(eng.vhost_path(domain)),
                 user["id"] if user["role"] != "admin" else None,
                 engine, php_version, ptype, port,
                 description, category,
                 datetime.now(timezone.utc).isoformat()),
            )
            site_id = cur.lastrowid
            for d in extra:
                conn.execute("INSERT INTO site_domains (site_id, domain) VALUES (?, ?)", (site_id, d))
            if php_version != "static":
                php_ops.create_pool(domain, php_version)
                php_ops.insert_php_block(domain, php_version, Path(eng.vhost_path(domain)), engine)
            if req.create_ftp:
                username = (req.ftp_username or "").strip() or domain.split(".")[0]
                password = (req.ftp_password or "").strip() or secrets.token_urlsafe(12)
                ftp_ops.create_account(username, password, site_id)
                ftp_created = True
                conn.execute(
                    "INSERT INTO ftp_accounts (site_id, username, password, created_at) VALUES (?, ?, ?, ?)",
                    (site_id, username, password, datetime.now(timezone.utc).isoformat()),
                )
            if req.create_db:
                db_name = (req.db_name or "").strip().lower() or domain.replace(".", "_")
                db_user = (req.db_user or "").strip().lower() or db_name
                if not validate.valid_db_name(db_name):
                    raise HTTPException(400, "Nama DB tidak valid (a-z, 0-9, _, max 64)")
                if not validate.valid_db_name(db_user):
                    raise HTTPException(400, "Username DB tidak valid (a-z, 0-9, _, max 64)")
                db_pass = (req.db_pass or "").strip() or secrets.token_urlsafe(12)
                if conn.execute("SELECT 1 FROM dbs WHERE db_name = ?", (db_name,)).fetchone():
                    raise HTTPException(409, "Nama DB sudah dipakai")
                database_ops.for_engine("mysql").create_db(db_name, db_user, db_pass, "localhost")
                conn.execute(
                    "INSERT INTO dbs (site_id, db_name, db_user, db_pass, db_host, db_type, owner_id, created_at) "
                    "VALUES (?, ?, ?, ?, 'localhost', 'mysql', ?, ?)",
                    (site_id, db_name, db_user, db_pass,
                     None if user["role"] == "admin" else user["id"],
                     datetime.now(timezone.utc).isoformat()),
                )
                db_created = (db_name, db_user, db_pass)
            if req.apply_ssl:
                cert_ops.install_ssl(domain, [domain] + extra)
            _log(conn, user, "site.create", domain + (f" +{len(extra)} alias" if extra else ""))
            conn.commit()
            row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        except Exception as e:
            # rollback: urut terbalik dari create
            if site_id is not None:
                conn.execute("DELETE FROM sites WHERE id = ?", (site_id,))
                conn.execute("DELETE FROM site_domains WHERE site_id = ?", (site_id,))
                conn.execute("DELETE FROM ftp_accounts WHERE site_id = ?", (site_id,))
                conn.execute("DELETE FROM dbs WHERE site_id = ?", (site_id,))
            if ftp_created:
                try:
                    ftp_ops.delete_account((req.ftp_username or "").strip() or domain.split(".")[0])
                except Exception:
                    pass
            if db_created:
                try:
                    database_ops.for_engine("mysql").drop_db(db_created[0], db_created[1], "localhost")
                except Exception:
                    pass
            if php_version != "static":
                try:
                    php_ops.remove_pool(domain, php_version)
                    php_ops.remove_php_block(domain, Path(eng.vhost_path(domain)), engine)
                except Exception:
                    pass
            try:
                eng.remove_site(domain)
            except Exception:
                pass
            if front_done:
                try:
                    webserver_ops.for_engine("nginx").remove_vhost(domain)
                except Exception:
                    pass
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(500, str(e)) from e
        return _site_row(row, conn)

@app.get("/api/php/versions")
def php_versions(user: dict = Depends(require_auth)) -> dict:
    return {"versions": ["static"] + php_ops.PHP_VERSIONS}

@app.get("/api/sites", response_model=list[SiteResponse] | dict)
def list_sites(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "asc",
    user: dict = Depends(require_auth),
) -> list[SiteResponse] | dict:
    from .deps import app_state

    start, length, draw = dt_params(start, length, draw)
    sql = "SELECT * FROM sites"
    conds: list[str] = []
    search_conds: list[str] = []
    args: list = []
    if user["role"] != "admin":
        conds.append("owner_id = ?")
        args.append(user["id"])
    if search:
        s = f"%{search.strip()}%"
        search_conds.append("(domain LIKE ? OR description LIKE ? OR category LIKE ?)")
        args.extend([s, s, s])
    all_conds = conds + search_conds
    where = (" WHERE " + " AND ".join(all_conds)) if all_conds else ""
    with db_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM sites" + (f" WHERE {' AND '.join(conds)}" if conds else ""),
            args[:len(conds)],
        ).fetchone()[0]
        filtered = conn.execute("SELECT COUNT(*) FROM sites" + where, args).fetchone()[0]
        rows = conn.execute(
            sql + where + dt_order(["id", "domain", "enabled", "created_at"], order_col, order_dir)
            + (" LIMIT ? OFFSET ?" if length else ""),
            args + ([length, start] if length else []),
        ).fetchall()
        out = []
        for r in rows:
            sr = _site_row(r, conn)
            app = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (r["id"],)).fetchone()
            if app is not None:
                sr.app = {
                    "id": app["id"], "app_type": app["app_type"], "port": app["port"],
                    "entry": app["entry"], "subpath": app["subpath"],
                    "state": app_state(r["domain"], r["root_path"], app["app_type"]),
                }
            out.append(sr)
    return dt_response(out, start, length, total, filtered, draw)

@app.post("/api/sites/{site_id}/enable")
def enable_site(site_id: int, user: dict = Depends(require_auth)) -> dict:
    return _set_enabled(site_id, True, user)

@app.post("/api/sites/{site_id}/disable")
def disable_site(site_id: int, user: dict = Depends(require_auth)) -> dict:
    return _set_enabled(site_id, False, user)

@app.post("/api/sites/{site_id}/fix-ownership")
def fix_site_ownership(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Fix directory ownership for vhost.

    Use this to fix LiteSpeed/Apache warnings on existing vhosts that were
    created with root ownership. Requires running as root.
    """    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        eng = webserver_ops.for_engine(row["webserver"])
        try:
            eng.fix_vhost_ownership(row["domain"])
        except (AttributeError, webserver_ops.WebserverError) as e:
            raise HTTPException(500, f"Failed to fix ownership: {str(e)}") from e _log(conn, user, "site.fix_ownership", row["domain"])
    return {"ok": True, "message": "Vhost ownership fixed"}

def _set_enabled(site_id: int, enabled: bool, user: dict) -> dict:
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        eng = webserver_ops.for_engine(row["webserver"])
        try:
            eng.set_enabled(row["domain"], enabled)
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET enabled = ? WHERE id = ?", (int(enabled), site_id))
        _log(conn, user, "site.enable" if enabled else "site.disable", row["domain"])
    return {"ok": True, "enabled": enabled}

@app.post("/api/sites/{site_id}/waf")
def waf_toggle(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Toggle WAF per-site. Khusus engine nginx (rules `if` nginx)."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["webserver"] != "nginx":
            raise HTTPException(400, f"WAF hanya untuk site nginx (site ini: {row['webserver']})")
        vhost = Path(row["vhost_path"])
        enabled = not bool(row["waf_enabled"])
        try:
            (waf_ops.enable if enabled else waf_ops.disable)(row["domain"], vhost)
            webserver_ops.for_engine("nginx").nginx_test()
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET waf_enabled = ? WHERE id = ?", (int(enabled), site_id))
        _log(conn, user, "waf.enable" if enabled else "waf.disable", row["domain"])
    webserver_ops.for_engine("nginx").nginx_reload()
    return {"ok": True, "waf_enabled": enabled}

@app.post("/api/sites/{site_id}/hotlink")
def hotlink_toggle(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Toggle hotlink protection per-site. Khusus engine nginx (valid_referers)."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["webserver"] != "nginx":
            raise HTTPException(400, f"Hotlink hanya untuk site nginx (site ini: {row['webserver']})")
        vhost = Path(row["vhost_path"])
        enabled = not bool(row["hotlink_enabled"])
        try:
            (hotlink_ops.enable if enabled else hotlink_ops.disable)(row["domain"], vhost)
            webserver_ops.for_engine("nginx").nginx_test()
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET hotlink_enabled = ? WHERE id = ?", (int(enabled), site_id))
        _log(conn, user, "hotlink.enable" if enabled else "hotlink.disable", row["domain"])
    webserver_ops.for_engine("nginx").nginx_reload()
    return {"ok": True, "hotlink_enabled": enabled}

class SitePhpUpdate(BaseModel):
    php_version: str

@app.put("/api/sites/{site_id}/php")
def update_site_php(site_id: int, req: SitePhpUpdate, user: dict = Depends(require_auth)) -> dict:
    """Update PHP version for a site. Valid values: static, php8.1, php8.2, php8.3"""
    valid_versions = ["static"] + php_ops.PHP_VERSIONS
    if req.php_version not in valid_versions:
        raise HTTPException(400, f"PHP version tidak valid. Pilihan: {', '.join(valid_versions)}")
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        old_version = row["php_version"]
        try:
            php_ops.set_php_version(row["domain"], old_version, req.php_version, Path(row["vhost_path"]), row["webserver"])
        except php_ops.PhpError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET php_version = ? WHERE id = ?", (req.php_version, site_id))
        _log(conn, user, "site.php-update", f"{row['domain']}: {old_version} -> {req.php_version}")
    return {"ok": True, "php_version": req.php_version}


# ==================== PHP CONFIGURATION API ====================

class PhpIniUpdate(BaseModel):
    ini: dict[str, str] = {}

@app.get("/api/sites/{site_id}/php-config")
def get_site_php_config(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Get PHP configuration for a site: ini, pool options, extensions."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        version = row["php_version"]
        return {
            "php_version": version,
            "ini": php_ops.get_ini(version),
            "common_ini_keys": php_ops.get_common_ini_keys(),
            "pool": php_ops.get_pool_options(row["domain"], version),
            "common_pool_keys": php_ops.get_common_pool_keys(),
            "extensions": php_ops.list_extensions(version),
        }

@app.put("/api/sites/{site_id}/php-config")
def update_site_php_config(site_id: int, req: PhpIniUpdate, user: dict = Depends(require_auth)) -> dict:
    """Update PHP ini settings for a site's PHP version."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        version = row["php_version"]
        for key, value in req.ini.items():
            if key not in php_ops.get_common_ini_keys():
                continue  # skip unknown keys
            try:
                php_ops.set_ini(version, key, value)
            except php_ops.PhpError as e:
                raise HTTPException(500, f"{key}: {e}") from e
        _log(conn, user, "site.php-ini-update", f"{row['domain']}: {list(req.ini.keys())}")
    return {"ok": True, "updated": list(req.ini.keys())}


class PhpPoolUpdate(BaseModel):
    pool: dict[str, str] = {}

@app.put("/api/sites/{site_id}/php-pool")
def update_site_php_pool(site_id: int, req: PhpPoolUpdate, user: dict = Depends(require_auth)) -> dict:
    """Update PHP-FPM pool options for a site."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        version = row["php_version"]
        for key, value in req.pool.items():
            if key not in php_ops.get_common_pool_keys():
                continue
            try:
                php_ops.set_pool_option(row["domain"], version, key, value)
            except php_ops.PhpError as e:
                raise HTTPException(500, f"{key}: {e}") from e
        _log(conn, user, "site.php-pool-update", f"{row['domain']}: {list(req.pool.keys())}")
    return {"ok": True, "updated": list(req.pool.keys())}


class PhpExtensionAction(BaseModel):
    extension: str

@app.post("/api/sites/{site_id}/php-extensions/enable")
def enable_site_php_extension(site_id: int, req: PhpExtensionAction, user: dict = Depends(require_auth)) -> dict:
    """Enable PHP extension for site's PHP version."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        try:
            php_ops.enable_extension(row["php_version"], req.extension)
        except php_ops.PhpError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "site.php-ext-enable", f"{row['domain']}: {req.extension}")
    return {"ok": True, "extension": req.extension, "enabled": True}

@app.post("/api/sites/{site_id}/php-extensions/disable")
def disable_site_php_extension(site_id: int, req: PhpExtensionAction, user: dict = Depends(require_auth)) -> dict:
    """Disable PHP extension for site's PHP version."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        try:
            php_ops.disable_extension(row["php_version"], req.extension)
        except php_ops.PhpError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "site.php-ext-disable", f"{row['domain']}: {req.extension}")
    return {"ok": True, "extension": req.extension, "enabled": False}

@app.post("/api/sites/{site_id}/php-extensions/install")
def install_site_php_extension(site_id: int, req: PhpExtensionAction, user: dict = Depends(require_auth)) -> dict:
    """Install PHP extension via apt untuk site's PHP version. Async + live output."""
    import time as _t
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["php_version"] == "static" or row["php_version"] not in php_ops.PHP_VERSIONS:
            raise HTTPException(400, "Site tidak menggunakan PHP-FPM")
        key = f"php-ext:{row['php_version']}:{req.extension}:{int(_t.time())}"
        from core import tasks as tasks_ops
        tasks_ops.start(key, lambda: php_ops.install_extension_task(row["php_version"], req.extension, key))
        _log(conn, user, "site.php-ext-install", f"{row['domain']}: {req.extension}")
    return {"ok": True, "extension": req.extension, "key": key}

@app.get("/api/sites/php-extensions/tasks/{key}")
def php_extension_task_status(key: str, _=Depends(require_auth)):
    """Status + output task install PHP extension."""
    from core import tasks as tasks_ops
    return tasks_ops.status(key)


# ------------------------------------------------------- domain tambahan

def _add_domain_db(conn, site_id: int, domain: str) -> None:
    """Insert row site_domains. Raise HTTPException kalau duplikat."""
    if conn.execute("SELECT 1 FROM site_domains WHERE site_id = ? AND domain = ?", (site_id, domain)).fetchone():
        raise HTTPException(409, f"Domain {domain} sudah terpasang di site ini")
    conn.execute("INSERT INTO site_domains (site_id, domain) VALUES (?, ?)", (site_id, domain))

@app.post("/api/sites/{site_id}/domains")
def add_domain(site_id: int, req: DomainAdd, user: dict = Depends(require_auth)) -> dict:
    """Pasang domain tambahan (alias) ke site. Update server_name vhost."""
    domain = req.domain.strip().lower()
    if not validate.valid_domain(domain):
        raise HTTPException(400, "Domain tidak valid")
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        # domain utama site lain? site_domains lain?
        if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah jadi site utama")
        if conn.execute("SELECT 1 FROM site_domains WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai site lain")
        if row["webserver"] != "nginx":
            raise HTTPException(400, f"Alias domain hanya untuk site nginx (site ini: {row['webserver']})")
        _add_domain_db(conn, site_id, domain)
        names = [d for d in conn.execute(
            "SELECT domain FROM site_domains WHERE site_id = ?", (site_id,)).fetchall()]
        try:
            webserver_ops.nginx_set_server_names(row["domain"], [row["domain"], *(r["domain"] for r in names)])
        except webserver_ops.WebserverError as e:
            conn.execute("DELETE FROM site_domains WHERE site_id = ? AND domain = ?", (site_id, domain))
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "site.domain-add", f"{row['domain']}: +{domain}")
    return {"ok": True, "domain": domain}

@app.delete("/api/sites/{site_id}/domains/{domain}")
def remove_domain(site_id: int, domain: str, user: dict = Depends(require_auth)) -> dict:
    """Lepas domain tambahan. Domain utama (sites.domain) tidak bisa dihapus."""
    domain = domain.strip().lower()
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["domain"] == domain:
            raise HTTPException(400, "Domain utama tidak bisa dihapus lewat sini")
        if not conn.execute("SELECT 1 FROM site_domains WHERE site_id = ? AND domain = ?", (site_id, domain)).fetchone():
            raise HTTPException(404, f"Domain {domain} tidak terpasang")
        conn.execute("DELETE FROM site_domains WHERE site_id = ? AND domain = ?", (site_id, domain))
        names = [r["domain"] for r in conn.execute(
            "SELECT domain FROM site_domains WHERE site_id = ?", (site_id,)).fetchall()]
        try:
            webserver_ops.nginx_set_server_names(row["domain"], [row["domain"], *names])
        except webserver_ops.WebserverError as e:
            _add_domain_db(conn, site_id, domain)  # rollback row
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "site.domain-remove", f"{row['domain']}: -{domain}")
    return {"ok": True}

# ------------------------------------------------------- proxy penuh (port)

class ProxyToggle(BaseModel):
    enabled: bool

@app.post("/api/sites/{site_id}/proxy")
def toggle_proxy(site_id: int, req: ProxyToggle, user: dict = Depends(require_auth)) -> dict:
    """Mode proxy penuh: vhost listen di port site + location / -> localhost:port.
    Butuh site punya port. Nginx-only."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["webserver"] != "nginx":
            raise HTTPException(400, f"Proxy hanya untuk site nginx (site ini: {row['webserver']})")
        if req.enabled and not row["port"]:
            raise HTTPException(400, "Set port site dulu sebelum proxy ON (endpoint PUT /api/sites/{id}/port)")
        try:
            if req.enabled:
                webserver_ops.nginx_proxy_enable(row["domain"], row["port"])
            else:
                webserver_ops.nginx_proxy_disable(row["domain"])
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET proxy_enabled = ? WHERE id = ?", (int(req.enabled), site_id))
        _log(conn, user, "site.proxy" + ("-on" if req.enabled else "-off"), row["domain"])
    return {"ok": True, "proxy_enabled": req.enabled}

class PortUpdate(BaseModel):
    port: int

@app.put("/api/sites/{site_id}/port")
def update_site_port(site_id: int, req: PortUpdate, user: dict = Depends(require_auth)) -> dict:
    """Set port site (untuk proxy project). Kalau proxy sedang ON, terapkan
    langsung ke vhost (listen + proxy_pass)."""
    if not 1 <= req.port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        if row["webserver"] != "nginx":
            raise HTTPException(400, f"Proxy hanya untuk site nginx (site ini: {row['webserver']})")
        if row["proxy_enabled"]:
            try:
                webserver_ops.nginx_proxy_enable(row["domain"], req.port)
            except webserver_ops.WebserverError as e:
                raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE sites SET port = ? WHERE id = ?", (req.port, site_id))
        _log(conn, user, "site.port", f"{row['domain']}: {row['port']} -> {req.port}")
    return {"ok": True, "port": req.port}


@app.get("/api/test-trigger-error")
def trigger_error():
    raise ValueError("This is a simulated server error")

