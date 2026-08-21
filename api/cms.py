"""API CMS installer: katalog, deteksi, install."""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import cms as cms_ops
from core import database, validate

from .deps import _log, app, check_site_access, db_conn, require_auth


class CmsInstall(BaseModel):
    cms: str
    domain: str
    db_name: str = ""
    db_user: str = ""
    db_pass: str = ""
    php_version: str = "static"
    lang: str = ""
    wp_version: str = "latest"


@app.get("/api/cms")
def cms_catalog(user: dict = Depends(require_auth)) -> dict:
    return {"ok": True, "items": cms_ops.catalog()}


@app.get("/api/sites/{site_id}/cms")
def cms_detect(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Deteksi CMS terpasang di root site."""
    import re as _re
    with db_conn() as conn:
        site = check_site_access(conn, site_id, user)
        root = Path(site["root_path"])
        cms = cms_ops.detect(root)
        version = None
        lang = None
        if cms == "wordpress":
            version = cms_ops._wp_version(root)
            # baca WPLANG dari wp-config
            wc = root / "wp-config.php"
            if wc.exists():
                m = _re.search(
                    r"define\s*\(\s*'WPLANG'\s*,\s*'([^']+)'\s*\)", wc.read_text())
                if m:
                    lang = m.group(1)
    return {"domain": site["domain"], "cms": cms, "version": version, "lang": lang}


@app.post("/api/cms/install")
def cms_install(req: CmsInstall, user: dict = Depends(require_auth)) -> dict:
    """Install CMS ke site. domain = site yang sudah ada."""
    cms = req.cms.strip().lower()
    domain = req.domain.strip().lower()
    if cms not in cms_ops.CMS_CATALOG:
        raise HTTPException(
            400, f"CMS tidak dikenal. Pilihan: {', '.join(cms_ops.CMS_CATALOG)}")
    if not validate.valid_domain(domain):
        raise HTTPException(400, "Domain tidak valid")

    # PHP version: hanya utk WordPress (CMS berbasis PHP); validasi
    php_version = (req.php_version or "static").strip().lower()
    from core import php as php_ops
    if cms == "wordpress":
        if php_version != "static" and php_version not in php_ops.PHP_VERSIONS:
            raise HTTPException(
                400, f"PHP version tidak valid. Pilihan: {', '.join(php_ops.PHP_VERSIONS)}")
    else:
        php_version = "static"

    # bahasa: hanya utk WordPress
    lang = (req.lang or "").strip()
    meta = cms_ops.CMS_CATALOG[cms]
    if lang and lang not in meta.get("languages", {}):
        raise HTTPException(400, f"Bahasa tidak didukung untuk {meta['name']}")

    # versi WordPress
    wp_version = (req.wp_version or "latest").strip()
    if cms == "wordpress" and wp_version not in cms_ops.WP_VERSIONS:
        raise HTTPException(
            400, f"Versi WordPress tidak valid. Pilihan: {', '.join(cms_ops.WP_VERSIONS)}")

    # DB auto-generate kalau kosong (hanya a-z0-9_ valid utk nama DB)
    db_name = (req.db_name or "").strip().lower(
    ) or re.sub(r"[^a-z0-9_]", "_", domain)
    db_user = (req.db_user or "").strip().lower() or db_name[:16]
    db_pass = (req.db_pass or "").strip() or secrets.token_urlsafe(12)
    for label, val in (("Nama DB", db_name), ("Username DB", db_user)):
        if not validate.valid_db_name(val):
            raise HTTPException(
                400, f"{label} tidak valid (a-z, 0-9, _, max 64)")
    if not db_pass or len(db_pass) > 128:
        raise HTTPException(400, "Password DB tidak valid (1-128 char)")

    # site harus ada + akses
    with db_conn() as conn:
        site = check_site_access(
            conn, int(_site_id_by_domain(conn, domain)), user)
    if not Path(site["root_path"]).is_dir():
        raise HTTPException(
            400, f"Folder root site tidak ada: {site['root_path']}")

    # DB name harus unik
    with db_conn() as conn:
        if conn.execute("SELECT 1 FROM dbs WHERE db_name = ?", (db_name,)).fetchone():
            raise HTTPException(409, f"Nama DB sudah dipakai: {db_name}")

    try:
        res = cms_ops.install(cms, domain, db_name, db_user, db_pass,
                              php_version=php_version, lang=lang or None,
                              wp_version=wp_version)
    except cms_ops.CmsError as e:
        raise HTTPException(500, str(e)) from e

    # register DB di panel (DB sudah dibuat di core.cms.install)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO dbs (site_id, db_name, db_user, db_pass, db_host, db_type, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, 'localhost', 'mysql', NULL, ?)",
            (site["id"], db_name, db_user, db_pass,
             datetime.now(timezone.utc).isoformat()),
        )
        # simpan PHP version + project_type php utk site (pool sudah dibuat)
        if cms == "wordpress" and php_version != "static":
            conn.execute(
                "UPDATE sites SET php_version = ?, project_type = 'php' WHERE id = ?",
                (php_version, site["id"]),
            )
        conn.commit()
    _log(None, user, "cms.install",
         f"{cms} → {domain} (db {db_name}, php {php_version}, lang {lang or 'en_US'}, v{res.get('version') or wp_version})")
    return {"ok": True, **res}


def _site_id_by_domain(conn, domain: str) -> int:
    row = conn.execute(
        "SELECT id FROM sites WHERE domain = ?", (domain,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Site tidak ada: {domain}")
    return row["id"]
