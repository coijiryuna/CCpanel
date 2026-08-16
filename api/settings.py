"""API settings: engine web server + database."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import database as database_ops
from core import monitor as monitor_ops
from core import webserver as webserver_ops

from .deps import _log, app, db_conn, require_admin


class WebserverSettings(BaseModel):
    engine: str


@app.get("/api/server/info")
def get_server_info(user: dict = Depends(require_admin)) -> dict:
    """Info server: CPU, RAM, load, disk. Admin only — data host sensitif."""
    return monitor_ops.server_info()


@app.get("/api/settings/webserver")
def get_webserver_settings(user: dict = Depends(require_admin)) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'webserver'").fetchone()
    return {"engine": row["value"] if row else webserver_ops.ACTIVE}


@app.post("/api/settings/webserver")
def set_webserver_settings(req: WebserverSettings, user: dict = Depends(require_admin)) -> dict:
    """Ganti engine web server global. Site baru pakai engine ini;
    site lama tetap di engine aslinya sampai dihapus/direstore."""
    engine = req.engine.strip().lower()
    if engine not in webserver_ops.ENGINES:
        raise HTTPException(400, f"Engine tidak dikenal: {engine}")
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('webserver', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (engine,),
        )
        _log(conn, user, "settings.webserver", engine)
    webserver_ops.set_active(engine)
    return {"ok": True, "engine": engine}


class WebserverMode(BaseModel):
    mode: str


@app.get("/api/settings/webserver-mode")
def get_webserver_mode(user: dict = Depends(require_admin)) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'webserver_mode'").fetchone()
    mode = row["value"] if row else webserver_ops.mode()
    return {"mode": mode if mode in webserver_ops.MODES else "single"}


@app.post("/api/settings/webserver-mode")
def set_webserver_mode(req: WebserverMode, user: dict = Depends(require_admin)) -> dict:
    """Ganti mode arsitektur web server: single / multi.

    single — engine aktif pegang 80/443 sendiri.
    multi  — nginx front di 80/443, apache backend 8288, OpenLiteSpeed 8188.
    Site yang sudah ada TIDAK diubah otomatis; mode berlaku utk vhost baru /
    switch engine berikutnya.
    """
    mode = (req.mode or "").strip().lower()
    if mode not in webserver_ops.MODES:
        raise HTTPException(
            400, f"Mode tidak dikenal. Pilihan: {', '.join(webserver_ops.MODES)}")
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('webserver_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (mode,),
        )
        _log(conn, user, "settings.webserver-mode", mode)
    webserver_ops.set_mode(mode)
    return {"ok": True, "mode": mode}


class DatabaseSettings(BaseModel):
    engine: str


@app.get("/api/settings/database")
def get_database_settings(user: dict = Depends(require_admin)) -> dict:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'database'").fetchone()
    return {"engine": row["value"] if row else database_ops.ACTIVE}


@app.post("/api/settings/database")
def set_database_settings(req: DatabaseSettings, user: dict = Depends(require_admin)) -> dict:
    engine = req.engine.strip().lower()
    if engine not in database_ops.ENGINES:
        raise HTTPException(400, f"Database engine tidak dikenal: {engine}")
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('database', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (engine,),
        )
        _log(conn, user, "settings.database", engine)
    database_ops.set_active(engine)
    return {"ok": True, "engine": engine}
