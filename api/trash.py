"""API trash: daftar, restore, purge site."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import webserver as webserver_ops

from .deps import _log, app, dt_params, dt_response, db_conn, require_admin

class TrashItem(BaseModel):
    name: str
    size: int
    mtime: float

@app.get("/api/trash", response_model=list[TrashItem] | dict)
def list_trash(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "asc",
    user: dict = Depends(require_admin),
) -> list[TrashItem] | dict:
    start, length, draw = dt_params(start, length, draw)
    try:
        items = [TrashItem(**i) for i in webserver_ops.trash_items()]
    except webserver_ops.WebserverError as e:
        raise HTTPException(500, str(e)) from e
    if search:
        s = search.strip().lower()
        items = [i for i in items if s in i.name.lower()]
    # sort in-memory: kolom whitelist, arah aman
    col = (order_col or "").strip().lower()
    if col.isdigit():
        col = ["name", "size", "mtime"][int(col)] if int(col) < 3 else "name"
    if col not in ("name", "size", "mtime"):
        col = "name"
    items.sort(key=lambda i: getattr(i, col), reverse=(order_dir or "").strip().lower() == "desc")
    total = len(items)
    page = items[start:start + length] if length else items
    return dt_response(page, start, length, total, total, draw)

@app.post("/api/trash/{name}/restore")
def restore_site(name: str, user: dict = Depends(require_admin)) -> dict:
    """Pindah folder trash balik ke wwwroot + tulis vhost + reload. Site aktif lagi."""
    try:
        domain = webserver_ops.restore_site(name)
    except webserver_ops.WebserverError as e:
        raise HTTPException(500, str(e)) from e
    with db_conn() as conn:
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
