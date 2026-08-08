"""API settings: engine web server + database."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import database as database_ops
from core import monitor as monitor_ops
from core import webserver as webserver_ops

from .deps import _log, app, get_db, require_admin

class WebserverSettings(BaseModel):
    engine: str

@app.get("/api/server/info")
def get_server_info(user: dict = Depends(require_admin)) -> dict:
    """Info server: CPU, RAM, load, disk. Admin only — data host sensitif."""
    return monitor_ops.server_info()

@app.get("/api/settings/webserver")
def get_webserver_settings(user: dict = Depends(require_admin)) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'webserver'").fetchone()
    return {"engine": row["value"] if row else webserver_ops.ACTIVE}

@app.post("/api/settings/webserver")
def set_webserver_settings(req: WebserverSettings, user: dict = Depends(require_admin)) -> dict:
    """Ganti engine web server global. Site baru pakai engine ini;
    site lama tetap di engine aslinya sampai dihapus/direstore."""
    engine = req.engine.strip().lower()
    if engine not in webserver_ops.ENGINES:
        raise HTTPException(400, f"Engine tidak dikenal: {engine}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('webserver', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (engine,),
        )
        _log(conn, user, "settings.webserver", engine)
    webserver_ops.set_active(engine)
    return {"ok": True, "engine": engine}

class DatabaseSettings(BaseModel):
    engine: str

@app.get("/api/settings/database")
def get_database_settings(user: dict = Depends(require_admin)) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'database'").fetchone()
    return {"engine": row["value"] if row else database_ops.ACTIVE}

@app.post("/api/settings/database")
def set_database_settings(req: DatabaseSettings, user: dict = Depends(require_admin)) -> dict:
    engine = req.engine.strip().lower()
    if engine not in database_ops.ENGINES:
        raise HTTPException(400, f"Database engine tidak dikenal: {engine}")
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('database', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (engine,),
        )
        _log(conn, user, "settings.database", engine)
    database_ops.set_active(engine)
    return {"ok": True, "engine": engine}
