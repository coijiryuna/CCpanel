"""API vhost config: baca/tulis file config vhost + fitur per-site + switch engine."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Request

from core import php as php_ops
from core import siteconfig as siteconfig_ops
from core import webserver as webserver_ops

from .deps import _log, app, check_site_access, get_db, require_auth

@app.get("/api/sites/{site_id}/vhost-config")
def get_vhost_config(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Isi konfigurasi vhost — untuk tombol Edit Config."""
    with get_db() as conn:
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
    with get_db() as conn:
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
    """State fitur site: rewrite rules, anti-XSS, access log + engine + vhost."""
    with get_db() as conn:
        row = check_site_access(conn, site_id, user)
        domain = row["domain"]
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(500, f"vhost {vh} tidak ada")
        content = vh.read_text()
        feats = siteconfig_ops.state(domain)
    return {
        "engine": row["webserver"],
        "vhost_path": str(vh),
        "vhost_content": content,
        "rewrite_rules": feats["rewrite_rules"],
        "xss_enabled": feats["xss_enabled"],
        "accesslog_enabled": feats["accesslog_enabled"],
    }


@app.put("/api/sites/{site_id}/config")
async def put_site_config(site_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Simpan fitur site: rewrite rules, anti-XSS, access log. Test + reload."""
    import json

    try:
        body = await req.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None

    with get_db() as conn:
        row = check_site_access(conn, site_id, user)
        domain = row["domain"]
        vh = Path(row["vhost_path"])
        if not vh.exists():
            raise HTTPException(400, f"vhost {vh} tidak ada")
        eng = webserver_ops.for_engine(row["webserver"])
        try:
            # vhost content dulu (semua engine) — nanti fitur sisip include ke file ini
            if "vhost_content" in body:
                vh.write_text(body["vhost_content"])
            # fitur rewrite/xss/accesslog HANYA nginx
            if row["webserver"] != "nginx":
                if any(k in body for k in ("rewrite_rules", "xss_enabled", "accesslog_enabled")):
                    raise siteconfig_ops.Error(
                        f"Rewrite/XSS/Access log hanya untuk site nginx (site ini: {row['webserver']})"
                    )
            else:
                # rewrite rules
                if "rewrite_rules" in body:
                    siteconfig_ops.set_rewrite(domain, body.get("rewrite_rules", ""), vh)
                # anti-xss
                if "xss_enabled" in body:
                    siteconfig_ops.set_xss(domain, bool(body["xss_enabled"]), vh)
                # access log
                if "accesslog_enabled" in body:
                    siteconfig_ops.set_accesslog(domain, bool(body["accesslog_enabled"]), vh)
            eng.nginx_test()
        except (webserver_ops.WebserverError, siteconfig_ops.Error) as e:
            raise HTTPException(400, str(e)) from e
        _log(conn, user, "site.config", domain)
    eng.nginx_reload()
    return {"ok": True}


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

    with get_db() as conn:
        row = check_site_access(conn, site_id, user)
        domain = row["domain"]
        old_engine = row["webserver"]
        if engine == old_engine:
            return {"ok": True, "engine": engine}

        old_eng = webserver_ops.for_engine(old_engine)
        new_eng = webserver_ops.for_engine(engine)
        old_vhost = Path(row["vhost_path"])
        old_content = old_vhost.read_text() if old_vhost.exists() else ""
        php_version = row["php_version"]
        root = Path(row["root_path"])
        multi = webserver_ops.is_multi()
        # validasi SEBELUM hapus apa pun — kalau root hilang, jangan sentuh vhost lama
        if not root.is_dir():
            raise HTTPException(400, f"Folder root tidak ada: {root}")

        try:
            # 1. hapus vhost lama (root tetap)
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
                    # front proxy sudah ada (static/proxy), replace ke port backend baru
                    if old_engine != "nginx":
                        webserver_ops.for_engine("nginx").remove_vhost(domain)
                    new_eng.activate_site(domain)
                    webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port(engine))
                    new_vhost = new_eng.vhost_path(domain)
            else:
                new_eng.activate_site(domain)
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
                old_eng.activate_site(domain)
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
