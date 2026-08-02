"""API apps: app runner per-site (node/python/go/docker) + proxy subpath."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from core import apps as apps_ops
from core import webserver as webserver_ops

from .deps import (
    _log,
    app,
    app_state,
    check_site_access,
    get_db,
    require_auth,
    validate_subpath,
)

class AppCreate(BaseModel):
    app_type: str
    port: int | None = None
    entry: str | None = None
    subpath: str | None = None
    name: str | None = None          # nama project (PM2)
    run_opt: str | None = None       # startup command tambahan
    user: str | None = None          # user systemd (default www)
    node_version: str | None = None  # v22/v20/...
    pm2: bool = False                # pakai PM2
    remark: str | None = None        # catatan

class AppResponse(BaseModel):
    id: int
    site_id: int
    app_type: str
    port: int
    entry: str
    subpath: str
    state: str
    detail: str = ""
    name: str = ""
    run_opt: str = ""
    user: str = ""
    node_version: str = ""
    pm2: bool = False
    remark: str = ""

def _app_row(conn, row, site) -> AppResponse:
    try:
        st = apps_ops.app_status(site["domain"], Path(site["root_path"]), row["app_type"])
        state, detail = st["state"], st["detail"]
    except apps_ops.AppError:
        state, detail = "error", ""
    return AppResponse(
        id=row["id"], site_id=row["site_id"], app_type=row["app_type"],
        port=row["port"], entry=row["entry"], subpath=row["subpath"],
        state=state, detail=detail,
        name=row["name"] if "name" in row.keys() else "",
        run_opt=row["run_opt"] if "run_opt" in row.keys() else "",
        user=row["user"] if "user" in row.keys() else "",
        node_version=row["node_version"] if "node_version" in row.keys() else "",
        pm2=bool(row["pm2"]) if "pm2" in row.keys() else False,
        remark=row["remark"] if "remark" in row.keys() else "",
    )

def _check_nginx(row) -> None:
    if row["webserver"] != "nginx":
        raise HTTPException(400, f"Aplikasi hanya untuk site nginx (site ini: {row['webserver']})")

@app.get("/api/sites/{site_id}/apps", response_model=list[AppResponse])
def list_apps(site_id: int, user: dict = Depends(require_auth)) -> list[AppResponse]:
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        rows = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchall()
    return [_app_row(conn, r, site) for r in rows]

@app.post("/api/sites/{site_id}/apps", response_model=AppResponse)
def create_app(site_id: int, req: AppCreate, user: dict = Depends(require_auth)) -> AppResponse:
    """Pasang aplikasi per-site. nginx-only (proxy subpath syntax nginx)."""
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        _check_nginx(site)
        if conn.execute("SELECT 1 FROM site_apps WHERE site_id = ?", (site_id,)).fetchone():
            raise HTTPException(409, "Site sudah punya aplikasi — hapus dulu atau gunakan endpoint update")
        app_type = req.app_type.lower()
        if app_type not in apps_ops.APP_TYPES:
            raise HTTPException(400, f"Tipe aplikasi tidak valid. Pilihan: {', '.join(apps_ops.APP_TYPES)}")
        entry = (req.entry or apps_ops.DEFAULT_ENTRY[app_type]).strip()
        port = req.port or 8000
        subpath = validate_subpath(req.subpath) if req.subpath else ""
        user = (req.user or apps_ops.DEFAULT_USER).strip() or apps_ops.DEFAULT_USER
        run_opt = (req.run_opt or "").strip()
        name = (req.name or "").strip()
        node_version = (req.node_version or "").strip()
        if node_version and node_version not in apps_ops.NODE_VERSIONS:
            raise HTTPException(400, f"Versi node tidak valid. Pilihan: {', '.join(apps_ops.NODE_VERSIONS)}")
        remark = (req.remark or "").strip()
        root = Path(site["root_path"])
        try:
            apps_ops.create_app(site["domain"], root, app_type, port, entry,
                                user=user, run_opt=run_opt, pm2=req.pm2,
                                name=name, node_version=node_version)
            if subpath:
                webserver_ops.nginx_proxy_insert(site["domain"], subpath, port)
        except (apps_ops.AppError, webserver_ops.WebserverError) as e:
            raise HTTPException(500, str(e)) from e
        cur = conn.execute(
            "INSERT INTO site_apps (site_id, app_type, port, entry, subpath, name, run_opt, user, node_version, pm2, remark, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (site_id, app_type, port, entry, subpath, name, run_opt, user,
             node_version, 1 if req.pm2 else 0, remark,
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "app.create", f"{site['domain']}: {app_type} port {port}")
        row = conn.execute("SELECT * FROM site_apps WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _app_row(conn, row, site)

@app.get("/api/node/versions")
def node_versions(user: dict = Depends(require_auth)) -> dict:
    return {"versions": apps_ops.node_versions()}

@app.post("/api/sites/{site_id}/apps/action")
async def app_action(site_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """start/stop/restart/status via JSON body {action}."""
    import json

    try:
        body = await req.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None
    action = body.get("action", "")
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        row = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Site tidak punya aplikasi")
        try:
            apps_ops.app_action(site["domain"], Path(site["root_path"]), row["app_type"], action)
            st = apps_ops.app_status(site["domain"], Path(site["root_path"]), row["app_type"])
        except apps_ops.AppError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, f"app.{action}", site["domain"])
    return {"ok": True, "state": st["state"], "detail": st["detail"]}

@app.get("/api/sites/{site_id}/apps/log")
def app_log(site_id: int, lines: int = 100, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        row = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Site tidak punya aplikasi")
        try:
            text = apps_ops.log_tail(site["domain"], Path(site["root_path"]), row["app_type"], lines)
        except apps_ops.AppError as e:
            raise HTTPException(500, str(e)) from e
    return {"log": text}

@app.put("/api/sites/{site_id}/apps", response_model=AppResponse)
def update_app(site_id: int, req: AppCreate, user: dict = Depends(require_auth)) -> AppResponse:
    """Ubah port/entry/subpath. Tulis ulang unit + proxy."""
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        _check_nginx(site)
        row = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Site tidak punya aplikasi")
        app_type = req.app_type or row["app_type"]
        entry = (req.entry or row["entry"]).strip()
        port = req.port or row["port"]
        subpath = validate_subpath(req.subpath) if req.subpath else row["subpath"]
        user = (req.user or row["user"] or apps_ops.DEFAULT_USER).strip()
        run_opt = (req.run_opt if req.run_opt is not None else row["run_opt"] or "").strip()
        name = (req.name if req.name is not None else row["name"] or "").strip()
        node_version = (req.node_version if req.node_version is not None else row["node_version"] or "").strip()
        if node_version and node_version not in apps_ops.NODE_VERSIONS:
            raise HTTPException(400, f"Versi node tidak valid. Pilihan: {', '.join(apps_ops.NODE_VERSIONS)}")
        pm2 = req.pm2 if req.pm2 is not None else bool(row["pm2"])
        remark = (req.remark if req.remark is not None else row["remark"] or "").strip()
        root = Path(site["root_path"])
        try:
            apps_ops.remove_app(site["domain"], root, row["app_type"])
            apps_ops.create_app(site["domain"], root, app_type, port, entry,
                                user=user, run_opt=run_opt, pm2=pm2,
                                name=name, node_version=node_version)
            if subpath:
                webserver_ops.nginx_proxy_insert(site["domain"], subpath, port)
        except (apps_ops.AppError, webserver_ops.WebserverError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute(
            "UPDATE site_apps SET app_type=?, port=?, entry=?, subpath=?, name=?, run_opt=?, user=?, node_version=?, pm2=?, remark=? WHERE id=?",
            (app_type, port, entry, subpath, name, run_opt, user, node_version,
             1 if pm2 else 0, remark, row["id"]),
        )
        _log(conn, user, "app.update", f"{site['domain']}: {app_type} port {port}")
        row2 = conn.execute("SELECT * FROM site_apps WHERE id = ?", (row["id"],)).fetchone()
    return _app_row(conn, row2, site)

@app.delete("/api/sites/{site_id}/apps")
def delete_app(site_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        site = check_site_access(conn, site_id, user)
        row = conn.execute("SELECT * FROM site_apps WHERE site_id = ?", (site_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Site tidak punya aplikasi")
        try:
            apps_ops.remove_app(site["domain"], Path(site["root_path"]), row["app_type"])
            if row["subpath"]:
                webserver_ops.nginx_proxy_remove(site["domain"], row["subpath"])
        except (apps_ops.AppError, webserver_ops.WebserverError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("DELETE FROM site_apps WHERE id = ?", (row["id"],))
        _log(conn, user, "app.delete", site["domain"])
    return {"ok": True}
