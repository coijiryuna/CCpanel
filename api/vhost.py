"""API vhost config: baca/tulis file config vhost + fitur per-site + switch engine."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.requests import Request
from core import php as php_ops
from core import siteconfig as siteconfig_ops
from core import webserver as webserver_ops

from .deps import _log, app, check_site_access, db_conn, require_auth

@app.get("/api/sites/{site_id}/vhost-config")
def get_vhost_config(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Isi konfigurasi vhost — untuk tombol Edit Config."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(500, f"vhost {vh} tidak ada")
        content = vh.read_text()
    return {"content": content, "path": str(vh), "engine": row["webserver"]}

@app.put("/api/sites/{site_id}/vhost-config")
async def put_vhost_config(site_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Simpan konfigurasi vhost -> test -> reload. Rollback kalau gagal."""
    import json

    try:
        body = await req.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None
    content = body.get("content", "")
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(400, f"vhost {vh} tidak ada")
        eng = webserver_ops.for_engine(row["webserver"])
        backup = vh.read_text()
        vh.write_text(content)
        try:
            eng.nginx_test()
        except webserver_ops.WebserverError as e:
            vh.write_text(backup)
            raise HTTPException(400, f"Konfigurasi ditolak: {e}") from e
        _log(conn, user, "site.vhost-edit", row["domain"])
    eng.nginx_reload()
    return {"ok": True}

# ------------------------------------------------------- fitur per-site (config)

@app.get("/api/sites/{site_id}/config")
def get_site_config(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """State fitur site: rewrite rules, anti-XSS, access log + engine + vhost + backend features.
    Multi mode + backend engine: return DUA vhost (nginx front + backend)."""
    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        domain = row["domain"]
        engine = row["webserver"]
        multi = webserver_ops.is_multi()
        
        # Backend vhost (engine-specific)
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(500, f"vhost {vh} tidak ada")
        backend_content = vh.read_text()
        backend_feats = _parse_backend_features(backend_content, engine)
        
        # Nginx front vhost (multi mode + backend engine)
        nginx_vhost_path = None
        nginx_content = None
        if multi and engine in ("apache", "litespeed"):
            nginx_vh = webserver_ops.nginx.vhost_path(domain)
            if nginx_vh.exists():
                nginx_vhost_path = str(nginx_vh)
                nginx_content = nginx_vh.read_text()
        
        feats = siteconfig_ops.state(domain)
    
    return {
        "engine": engine,
        "vhost_path": str(vh),
        "vhost_content": backend_content,
        "rewrite_rules": feats["rewrite_rules"],
        "xss_enabled": feats["xss_enabled"],
        "accesslog_enabled": feats["accesslog_enabled"],
        # Site directory & running directory
        "site_dir": row["site_dir"] if "site_dir" in row.keys() else "",
        "running_dir": row["running_dir"] if "running_dir" in row.keys() else "",
        # Apache/OLS features
        "deny_files_enabled": backend_feats.get("deny_files_enabled", True),
        "remote_ip_enabled": backend_feats.get("remote_ip_enabled", True),
        "deflate_enabled": backend_feats.get("deflate_enabled", True),
        "directory_index": backend_feats.get("directory_index", "index.php index.html index.htm default.php default.html default.htm"),
        "server_admin": backend_feats.get("server_admin", f"webmaster@{domain}"),
        "error_log_path": backend_feats.get("error_log_path", "/www/wwwlogs/"),
        "custom_log_path": backend_feats.get("custom_log_path", "/www/wwwlogs/"),
        # Multi mode: nginx front vhost
        "multi_mode": multi,
        "nginx_vhost_path": nginx_vhost_path,
        "nginx_vhost_content": nginx_content,
    }


@app.put("/api/sites/{site_id}/config")
async def put_site_config(site_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Simpan fitur site: rewrite rules, anti-XSS, access log + backend features. Test + reload.
    Multi mode + backend engine: handle DUA vhost (nginx front + backend)."""
    import json

    try:
        body = await req.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None

    with db_conn() as conn:
        row = check_site_access(conn, site_id, user)
        domain = row["domain"]
        engine = row["webserver"]
        multi = webserver_ops.is_multi()
        
        # Backend vhost
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(400, f"vhost {vh} tidak ada")
        eng = webserver_ops.for_engine(engine)
        
        # Nginx front vhost (multi mode + backend engine)
        nginx_vh = None
        if multi and engine in ("apache", "litespeed"):
            nginx_vh = webserver_ops.nginx.vhost_path(domain)
        
        try:
            # 1. Backend vhost content
            if "vhost_content" in body:
                vh.write_text(body["vhost_content"])
            
            # 2. Nginx front vhost content (multi mode + backend engine)
            if multi and engine in ("apache", "litespeed") and "nginx_vhost_content" in body:
                if nginx_vh and nginx_vh.exists():
                    nginx_vh.write_text(body["nginx_vhost_content"])
            
            # 3. fitur rewrite/xss/accesslog HANYA nginx front (multi mode) atau nginx engine
            if engine == "nginx":
                # Single mode nginx atau multi mode nginx engine
                if "rewrite_rules" in body:
                    siteconfig_ops.set_rewrite(domain, body.get("rewrite_rules", ""), vh)
                if "xss_enabled" in body:
                    siteconfig_ops.set_xss(domain, bool(body["xss_enabled"]), vh)
                if "accesslog_enabled" in body:
                    siteconfig_ops.set_accesslog(domain, bool(body["accesslog_enabled"]), vh)
            elif multi and engine in ("apache", "litespeed"):
                # Multi mode: nginx front handle rewrite/xss/accesslog
                if nginx_vh and nginx_vh.exists():
                    if "rewrite_rules" in body:
                        siteconfig_ops.set_rewrite(domain, body.get("rewrite_rules", ""), nginx_vh)
                    if "xss_enabled" in body:
                        siteconfig_ops.set_xss(domain, bool(body["xss_enabled"]), nginx_vh)
                    if "accesslog_enabled" in body:
                        siteconfig_ops.set_accesslog(domain, bool(body["accesslog_enabled"]), nginx_vh)
            
            # 4. Apache/OLS backend features
            if engine in ("apache", "litespeed"):
                _apply_backend_features(domain, engine, vh, body)
            
            # 5. Update site_dir and running_dir in database
            if "site_dir" in body or "running_dir" in body:
                site_dir = body.get("site_dir", row["site_dir"] if "site_dir" in row.keys() else "")
                running_dir = body.get("running_dir", row["running_dir"] if "running_dir" in row.keys() else "")
                conn.execute(
                    "UPDATE sites SET site_dir = ?, running_dir = ? WHERE id = ?",
                    (site_dir, running_dir, site_id)
                )
            
            # 6. Test both configs
            eng.nginx_test()
            if multi and engine in ("apache", "litespeed") and nginx_vh and nginx_vh.exists():
                webserver_ops.nginx.nginx_test()
        except (webserver_ops.WebserverError, siteconfig_ops.Error) as e:
            raise HTTPException(400, str(e)) from e
        _log(conn, user, "site.config", domain)
    
    # Reload both
    eng.nginx_reload()
    if multi and engine in ("apache", "litespeed"):
        webserver_ops.nginx.nginx_reload()
    return {"ok": True}


def _parse_backend_features(content: str, engine: str) -> dict:
    """Parse Apache/OLS features from vhost content."""
    if engine not in ("apache", "litespeed"):
        return {}
    import re
    return {
        "deny_files_enabled": "DENY FILES" in content and "Deny from all" in content,
        "remote_ip_enabled": "RemoteIPTrustedProxy" in content and "RemoteIPHeader" in content,
        "deflate_enabled": "SetOutputFilter DEFLATE" in content,
        "directory_index": re.search(r"DirectoryIndex\s+([^\n]+)", content).group(1).strip() if re.search(r"DirectoryIndex\s+([^\n]+)", content) else "",
        "server_admin": re.search(r"ServerAdmin\s+([^\n]+)", content).group(1).strip() if re.search(r"ServerAdmin\s+([^\n]+)", content) else "",
        "error_log_path": re.search(r'ErrorLog\s+"([^"]+)"', content).group(1).strip() if re.search(r'ErrorLog\s+"([^"]+)"', content) else "",
        "custom_log_path": re.search(r'CustomLog\s+"([^"]+)"', content).group(1).strip() if re.search(r'CustomLog\s+"([^"]+)"', content) else "",
    }

def _apply_backend_features(domain: str, engine: str, vh: Path, body: dict) -> None:
    """Regenerate vhost with updated Apache/OLS features."""
    from core import webserver as webserver_ops
    
    root = webserver_ops.root_path(domain)
    if not root.is_dir():
        return
    
    # Get current features from body
    deny_files = body.get("deny_files_enabled", True)
    remote_ip = body.get("remote_ip_enabled", True)
    deflate = body.get("deflate_enabled", True)
    directory_index = body.get("directory_index", "index.php index.html index.htm default.php default.html default.htm")
    server_admin = body.get("server_admin", f"webmaster@{domain}")
    error_log_path = body.get("error_log_path", "/www/wwwlogs/")
    custom_log_path = body.get("custom_log_path", "/www/wwwlogs/")
    running_dir = body.get("running_dir", "")
    
    if engine == "apache":
        # Regenerate apache vhost with features
        from core import apache as apache_ops
        apache_ops._write_vhost_with_features(domain, root, {
            "deny_files": deny_files,
            "remote_ip": remote_ip,
            "deflate": deflate,
            "directory_index": directory_index,
            "server_admin": server_admin,
            "error_log_path": error_log_path,
            "custom_log_path": custom_log_path,
            "running_dir": running_dir,
        })
    elif engine == "litespeed":
        # Regenerate OLS vhost with features
        from core import litespeed as litespeed_ops
        litespeed_ops._write_vhost_with_features(domain, root, {
            "deny_files": deny_files,
            "remote_ip": remote_ip,
            "deflate": deflate,
            "directory_index": directory_index,
            "server_admin": server_admin,
            "error_log_path": error_log_path,
            "custom_log_path": custom_log_path,
            "running_dir": running_dir,
        })


@app.post("/api/sites/{site_id}/engine")
async def switch_engine(site_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Ganti engine web server per-site. Root tetap; vhost + fitur dipindah.

    - hapus vhost lama (tanpa trash root)
    - buat vhost baru di engine target (folder root sama)
    - migrasi PHP block + fitur include (rewrite/xss/accesslog) ke vhost baru
    - update DB: webserver + vhost_path
    Rollback: kalau gagal, restore vhost lama.
    """
    import json

    try:
        body = json.loads(await req.body() or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None
    engine = (body.get("engine") or "").strip().lower()
    if engine not in webserver_ops.ENGINES:
        raise HTTPException(400, f"Web server tidak valid. Pilihan: {', '.join(webserver_ops.ENGINES)}")

    with db_conn() as conn:
        if engine == old_engine:
            return {"ok": True, "engine": engine}

        old_eng = webserver_ops.for_engine(old_engine)
        new_eng = webserver_ops.for_engine(engine)
        old_vhost = Path(row["vhost_path"])
        old_content = old_vhost.read_text() if old_vhost.exists() else ""
        php_version = row["php_version"]
        root = Path(row["root_path"])
        running_dir = row["running_dir"] if "running_dir" in row.keys() else ""
        multi = webserver_ops.is_multi()
        # validasi SEBELUM hapus apa pun — kalau root hilang, jangan sentuh vhost lama
        if not root.is_dir():
            raise HTTPException(400, f"Folder root tidak ada: {root}")

        try:
            # 1. hapus vhost lama (root tetap). multi + old==nginx: vhost nginx
            #    = front proxy, JANGAN dihapus — front_proxy_enable akan
            #    overwrite + preserve direktif SSL (site tetap HTTPS).
            if not (multi and old_engine == "nginx"):
                old_eng.remove_vhost(domain)
            # 2. buat vhost baru pakai folder root yang sama.
            #    multi mode: nginx front = proxy/static vhost di 80, backend
            #    engine = vhost di port backend. Switch engine backend punya
            #    nginx front yang harus dibalik/repasang.
            if multi:
                if engine == "nginx":
                    # backend -> nginx: hapus vhost backend, balik front ke static
                    webserver_ops.front_proxy_disable(domain)
                    new_vhost = webserver_ops.for_engine("nginx").vhost_path(domain)
                else:
                    # nginx -> backend / backend -> backend lain:
                    # front proxy sudah ada (static/proxy), replace ke port backend baru.
                    # SSL di front di-preserve otomatis oleh front_proxy_enable.
                    new_eng.activate_site(domain, running_dir)
                    webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port(engine))
                    new_vhost = new_eng.vhost_path(domain)
            else:
                new_eng.activate_site(domain, running_dir)
                new_vhost = new_eng.vhost_path(domain)
            # 3. migrasi PHP block
            if php_version != "static":
                php_ops.insert_php_block(domain, php_version, new_vhost, engine)
            # 4. migrasi fitur include (rewrite/xss/accesslog) — nginx-only
            siteconfig_ops.migrate_vhost(domain, old_content, new_vhost, engine)
            # 5. update DB
            conn.execute("UPDATE sites SET webserver = ?, vhost_path = ? WHERE id = ?",
                         (engine, str(new_vhost), site_id))
        except (webserver_ops.WebserverError, php_ops.PhpError) as e:
            # rollback: restore vhost lama
            try:
                old_eng.activate_site(domain, running_dir)
            except Exception:
                pass
            if multi:
                try:
                    if old_engine == "nginx":
                        webserver_ops.front_proxy_disable(domain)
                    else:
                        webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port(old_engine))
                except Exception:
                    pass
            raise HTTPException(500, f"Gagal pindah engine: {e}") from e
        _log(conn, user, "site.engine", f"{domain}: {old_engine} -> {engine}")
    return {"ok": True, "engine": engine}
