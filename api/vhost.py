"""API vhost config: baca/tulis file config vhost + rollback otomatis."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from core import webserver as webserver_ops

from .deps import _log, app, check_site_access, get_db, require_auth

@app.get("/api/sites/{site_id}/vhost-config")
def get_vhost_config(site_id: int, user: dict = Depends(require_auth)) -> dict:
    """Isi konfigurasi vhost — untuk tombol Edit Config."""
    with get_db() as conn:
        row = check_site_access(conn, site_id, user)
        try:
            content = webserver_ops.read_vhost(row["domain"])
        except webserver_ops.WebserverError as e:
            raise HTTPException(500, str(e)) from e
    return {"content": content, "path": row["vhost_path"], "engine": row["webserver"]}

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
        try:
            webserver_ops.write_vhost(row["domain"], content)
        except webserver_ops.WebserverError as e:
            raise HTTPException(400, f"Konfigurasi ditolak: {e}") from e
        _log(conn, user, "site.vhost-edit", row["domain"])
    return {"ok": True}
