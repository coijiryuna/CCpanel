"""API backup: daftar, buat, restore, hapus."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import backup as backup_ops
from core import webserver as webserver_ops

from .deps import _log, app, dt_params, dt_response, get_db, require_admin

class BackupItem(BaseModel):
    name: str
    type: str
    size: int
    mtime: float

@app.get("/api/backups", response_model=list[BackupItem] | dict)
def list_backups(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "asc",
    type: str | None = None,
    user: dict = Depends(require_admin),
) -> list[BackupItem] | dict:
    start, length, draw = dt_params(start, length, draw)
    try:
        items = [BackupItem(**i) for i in backup_ops.list_backups()]
    except backup_ops.BackupError as e:
        raise HTTPException(500, str(e)) from e
    if type in ("site", "db"):
        items = [i for i in items if i.type == type]
    if search:
        s = search.strip().lower()
        items = [i for i in items if s in i.name.lower() or s in i.type.lower()]
    # sort in-memory: kolom whitelist, arah aman
    col = (order_col or "").strip().lower()
    if col.isdigit():
        col = ["name", "type", "size", "mtime"][int(col)] if int(col) < 4 else "name"
    if col not in ("name", "type", "size", "mtime"):
        col = "name"
    items.sort(key=lambda i: getattr(i, col), reverse=(order_dir or "").strip().lower() == "desc")
    total = len(items)
    page = items[start:start + length] if length else items
    return dt_response(page, start, length, total, total, draw)

@app.post("/api/backups/site/{site_id}")
def backup_site(site_id: int, user: dict = Depends(require_admin)) -> dict:
    """Backup folder root site ke tar.gz."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Site tidak ada")
    try:
        dest = backup_ops.backup_site(row["domain"])
    except backup_ops.BackupError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "backup.site", row["domain"])
    return {"ok": True, "name": dest.name}

@app.post("/api/backups/db/{db_id}")
def backup_db(db_id: int, user: dict = Depends(require_admin)) -> dict:
    """Backup database ke sql.gz via mysqldump."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM dbs WHERE id = ?", (db_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "DB tidak ada")
    try:
        dest = backup_ops.backup_db(row["db_name"])
    except backup_ops.BackupError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "backup.db", row["db_name"])
    return {"ok": True, "name": dest.name}

@app.post("/api/backups/{name}/restore")
def restore_backup(name: str, user: dict = Depends(require_admin)) -> dict:
    """Restore backup. Site: extract folder + tulis vhost + row baru (kalau belum ada).
    DB: butuh body {db_name} — database harus sudah dibuat dulu (create_db)."""
    if name.endswith(".tar.gz"):
        try:
            root = backup_ops.restore_site(name)
        except backup_ops.BackupError as e:
            raise HTTPException(500, str(e)) from e
        domain = root.name
        with get_db() as conn:
            existing = conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone()
            if not existing:
                try:
                    webserver_ops.activate_site(domain)
                except webserver_ops.WebserverError as e:
                    # rollback folder biar tidak nyangkut
                    shutil.rmtree(root, ignore_errors=True)
                    raise HTTPException(500, str(e)) from e
                conn.execute(
                    "INSERT INTO sites (domain, root_path, vhost_path, enabled, webserver, created_at) "
                    "VALUES (?, ?, ?, 1, ?, ?)",
                    (domain, str(root), str(webserver_ops.vhost_path(domain)),
                     webserver_ops.ACTIVE,
                     datetime.now(timezone.utc).isoformat()),
                )
        _log(None, user, "backup.restore", f"site {domain}")
        return {"ok": True, "domain": domain}
    if name.endswith(".sql.gz"):
        db_name = name.rsplit(".sql.gz", 1)[0]
        try:
            backup_ops.restore_db(name, db_name)
        except backup_ops.BackupError as e:
            raise HTTPException(500, str(e)) from e
        _log(None, user, "backup.restore", f"db {db_name}")
        return {"ok": True, "db_name": db_name}
    raise HTTPException(400, "Nama backup tidak dikenal")

@app.delete("/api/backups/{name}")
def delete_backup(name: str, user: dict = Depends(require_admin)) -> dict:
    """Hapus file backup. Nama divalidasi — hanya isi BACKUP_DIR."""
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise HTTPException(400, "Nama backup tidak valid")
    try:
        target = (backup_ops.BACKUP_DIR / name).resolve()
        if backup_ops.BACKUP_DIR.resolve() not in target.parents:
            raise HTTPException(400, "Nama backup tidak valid")
        if not target.is_file():
            raise HTTPException(404, "Backup tidak ada")
        target.unlink()
    except OSError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "backup.delete", name)
    return {"ok": True}
