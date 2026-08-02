"""API SSL: pasang cert + renew manual."""
from __future__ import annotations

from fastapi import Depends, HTTPException

from core import cert as cert_ops

from .deps import _log, app, check_site_access, get_db, require_admin, require_auth

@app.post("/api/sites/{site_id}/ssl")
def install_ssl(site_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = check_site_access(conn, site_id, user)
    try:
        cert_ops.install_ssl(row["domain"])
    except cert_ops.CertError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "ssl.install", row["domain"])
    return {"ok": True}

@app.post("/api/ssl/renew")
def renew_ssl(user: dict = Depends(require_admin)) -> dict:
    """Renew semua cert yang mendekati expiry (jalan manual, sama seperti cron)."""
    try:
        cert_ops.renew_all()
    except cert_ops.CertError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "ssl.renew", "semua cert")
    return {"ok": True}
