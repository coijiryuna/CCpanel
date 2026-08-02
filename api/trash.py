"""API trash: daftar, restore, purge site."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import webserver as webserver_ops

from .deps import _log, app, get_db, require_admin

class TrashItem(BaseModel):
    name: str
    size: int
    mtime: float

@app.get("/api/trash", response_model=list[TrashItem])
def list_trash(user: dict = Depends(require_admin)) -> list[TrashItem]:
    try:
        return [TrashItem(**i) for i in webserver_ops.trash_items()]
    except webserver_ops.WebserverError as e:
        raise HTTPException(500, str(e)) from e

@app.post("/api/trash/{name}/restore")
def restore_site(name: str, user: dict = Depends(require_admin)) -> dict:
    """Pindah folder trash balik ke wwwroot + tulis vhost + reload. Site aktif lagi."""
    try:
        domain = webserver_ops.restore_site(name)
    except webserver_ops.WebserverError as e:
        raise HTTPException(500, str(e)) from e
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Site {domain} sudah ada di panel")
        conn.execute(
            "INSERT INTO sites (domain, root_path, vhost_path, enabled, webserver, php_version, created_at) "
            "VALUES (?, ?, ?, 1, ?, 'static', ?)",
            (domain, str(webserver_ops.root_path(domain)), str(webserver_ops.vhost_path(domain)),
             webserver_ops.ACTIVE,
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "trash.restore", domain)
    return {"ok": True, "domain": domain}

@app.delete("/api/trash/{name}")
def purge_site(name: str, user: dict = Depends(require_admin)) -> dict:
    """Hapus PERMANEN folder trash — tidak bisa dibatalkan."""
    try:
        webserver_ops.purge_site(name)
    except webserver_ops.WebserverError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "trash.purge", name)
    return {"ok": True}
