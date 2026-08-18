"""API settings: engine web server + database."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import database as database_ops
from core import monitor as monitor_ops
from core import webserver as webserver_ops

from .deps import _log, app, db_conn, require_admin

BASE_DIR = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    return Path(os.environ.get("CCPANEL_DATA_DIR", BASE_DIR / "data"))


def _panel_db_path() -> Path:
    return _data_dir() / "ccpanel.db"


def _drop_mysql_databases(conn) -> list[str]:
    rows = conn.execute("SELECT db_name, db_user, db_host FROM dbs").fetchall()
    dropped: list[str] = []
    for row in rows:
        db_engine = row["db_type"] if "db_type" in row.keys() else "mysql"
        if db_engine != "mysql":
            continue
        try:
            database_ops.drop_db(
                row["db_name"], row["db_user"], row["db_host"])
            dropped.append(row["db_name"])
        except Exception:
            pass
    return dropped


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


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


class FactoryResetRequest(BaseModel):
    confirm: str
    password: str


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


@app.post("/api/settings/factory-reset")
def factory_reset(req: FactoryResetRequest, user: dict = Depends(require_admin)) -> dict:
    """Reset panel total: hapus data site + config + DB website. Sisakan user login saja."""
    if req.confirm.strip() != "RESET-SEKARANG":
        raise HTTPException(400, "Konfirmasi salah")
    if not req.password:
        raise HTTPException(400, "Password admin wajib diisi")

    with db_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
        if row is None:
            raise HTTPException(401, "User tidak ada")
        import bcrypt
        if not bcrypt.checkpw(req.password.encode(), row["password_hash"].encode()):
            raise HTTPException(401, "Password salah")

        site_rows = conn.execute(
            "SELECT id, domain, root_path, vhost_path FROM sites").fetchall()
        db_rows = conn.execute(
            "SELECT db_name, db_user, db_host, db_type FROM dbs").fetchall()

        # drop DB website dulu
        dropped_dbs = []
        for row_db in db_rows:
            if row_db["db_type"] == "mysql":
                try:
                    database_ops.drop_db(
                        row_db["db_name"], row_db["db_user"], row_db["db_host"])
                    dropped_dbs.append(row_db["db_name"])
                except Exception:
                    pass

        # hapus folder/config site
        for row_site in site_rows:
            try:
                _remove_tree(Path(row_site["root_path"]))
            except Exception:
                pass
            try:
                Path(row_site["vhost_path"]).unlink(missing_ok=True)
            except Exception:
                pass
            try:
                webserver_ops.for_engine(
                    "nginx").remove_vhost(row_site["domain"])
            except Exception:
                pass
            try:
                webserver_ops.for_engine(
                    "apache").remove_vhost(row_site["domain"])
            except Exception:
                pass
            try:
                webserver_ops.for_engine(
                    "litespeed").remove_vhost(row_site["domain"])
            except Exception:
                pass

        # bersihkan tabel panel, sisakan user login
        conn.execute("DELETE FROM docker_domains")
        conn.execute("DELETE FROM cron_jobs")
        conn.execute("DELETE FROM projects")
        conn.execute("DELETE FROM site_domains")
        conn.execute("DELETE FROM site_apps")
        conn.execute("DELETE FROM ftp_accounts")
        conn.execute("DELETE FROM dbs")
        conn.execute("DELETE FROM sites")
        conn.execute(
            "DELETE FROM settings WHERE key NOT IN ('webserver','webserver_mode','database')")
        conn.execute("DELETE FROM audit_log")
        conn.execute("DELETE FROM users WHERE id != ?", (user["id"],))
        conn.commit()

    _remove_tree(_data_dir() / "backups")
    _remove_tree(
        Path(os.environ.get("CCPANEL_TRASH_DIR", BASE_DIR / "data" / "trash")))
    _remove_tree(
        Path(os.environ.get("CCPANEL_SITEFEAT_DIR", "/etc/nginx/sitefeat.d")))
    _remove_tree(
        Path(os.environ.get("CCPANEL_HOTLINK_DIR", "/etc/nginx/hotlink.d")))

    return {"ok": True, "dropped_dbs": len(dropped_dbs), "sites_removed": len(site_rows)}
