"""API App Store: katalog runtime + aplikasi pendukung, install/uninstall."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from core import appstore as store

from .deps import _log, app, db_conn, get_db, require_auth


@app.get("/api/appstore")
def appstore_list(_=Depends(require_auth), db=Depends(get_db)):
    return {"ok": True, "items": store.list_catalog(), "tasks": store.task_list()}


@app.post("/api/appstore/{item_id}/install")
def appstore_install(item_id: str, user: dict = Depends(require_auth), db=Depends(get_db)):
    """Mulai install async. Frontend polling /api/appstore/tasks/{key}."""
    try:
        res = store.start_task(item_id, "install")
    except store.AppStoreError as e:
        raise HTTPException(400, str(e))
    _log(db, user, "appstore.install", item_id)
    return res


@app.post("/api/appstore/{item_id}/uninstall")
def appstore_uninstall(item_id: str, user: dict = Depends(require_auth), db=Depends(get_db)):
    """Mulai uninstall async."""
    try:
        res = store.start_task(item_id, "uninstall")
    except store.AppStoreError as e:
        raise HTTPException(400, str(e))
    _log(db, user, "appstore.uninstall", item_id)
    return res

@app.get("/api/appstore/tasks/{key}")
def appstore_task_status(key: str, _=Depends(require_auth)):
    """Status + output task install/uninstall."""
    return store.task_status(key)

@app.post("/api/appstore/{item_id}/service/{action}")
def appstore_service(item_id: str, action: str, user: dict = Depends(require_auth), db=Depends(get_db)):
    """start/stop/restart/reload service systemd milik item app store."""
    try:
        res = store.service_action(item_id, action)
    except store.AppStoreError as e:
        raise HTTPException(400, str(e))
    _log(db, user, f"appstore.service.{action}", item_id)
    return res

@app.get("/api/appstore/{item_id}/service/status")
def appstore_service_status(item_id: str, _=Depends(require_auth)):
    """Status service systemd item (active/inactive/failed/'')."""
    return {"id": item_id, "status": store.service_status(item_id)}