"""API cron: auto-renew SSL."""
from __future__ import annotations

from fastapi import Depends, HTTPException

from core import cron as cron_ops

from .deps import _log, app, require_admin

@app.get("/api/cron/status")
def cron_status(user: dict = Depends(require_admin)) -> dict:
    try:
        return cron_ops.status()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e

@app.post("/api/cron/install")
def cron_install(user: dict = Depends(require_admin)) -> dict:
    """Pasang auto-renew SSL: script + crontab root. Idempoten."""
    try:
        res = cron_ops.install()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "cron.install", res.get("script", ""))
    return res

@app.post("/api/cron/uninstall")
def cron_uninstall(user: dict = Depends(require_admin)) -> dict:
    """Hapus auto-renew SSL: crontab line + script. Idempoten."""
    try:
        res = cron_ops.uninstall()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "cron.uninstall", "")
    return res
