"""CCPanel — hosting control panel backend.

Struktur:
  server.py   — startup + mount static (SPA). TIPIS.
  api/        — route per modul (auth, sites, apps, dbs, ...). Satu file per grup API.
  core/       — operasi sistem (nginx, php, database, cert, ...).

Jalankan: uvicorn server:app --host 127.0.0.1 --port 8888
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# register semua route API (import = register ke app via decorator)
from api import deps
from api import __init__ as _routes  # noqa: F401
from api.deps import STATIC_DIR, app, init_db
from core import database as database_ops
from core import webserver as webserver_ops

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    status_code = 500
    detail = str(exc)
    
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = exc.detail
    elif hasattr(exc, "status_code"):
        status_code = getattr(exc, "status_code")
        detail = getattr(exc, "detail", str(exc))
        
    if status_code >= 500:
        try:
            with open("/tmp/ccpanel_error.log", "a") as f:
                f.write(f"=== Error at {datetime.now(timezone.utc).isoformat()} ===\n")
                f.write(f"Method: {request.method} | Path: {request.url.path}\n")
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
                f.write("\n")
        except Exception:
            pass
            
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
    )

init_db()

# engine web server aktif: env override (testing), kalau tidak dari DB settings
if not os.environ.get("CCPANEL_WEBSERVER"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'webserver'").fetchone()
        if row:
            webserver_ops.set_active(row["value"])
        else:
            # Default to nginx if no setting found
            webserver_ops.set_active("nginx")

# mode web server (single/multi): env override (testing), kalau tidak dari DB
if not os.environ.get("CCPANEL_WEBSERVER_MODE"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'webserver_mode'").fetchone()
        if row and row["value"] in webserver_ops.MODES:
            webserver_ops.set_mode(row["value"])
        else:
            # Default to single if no setting found
            webserver_ops.set_mode("single")

# engine database aktif: env override (testing), kalau tidak dari DB settings
if not os.environ.get("CCPANEL_DATABASE"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'database'").fetchone()
        if row:
            database_ops.set_active(row["value"])
        else:
            # Default to mysql if no setting found
            database_ops.set_active("mysql")

# ----------------------------------------------------------------- static
# Mount TERAKHIR — setelah semua route API. Mount "/" menangkap semua request
# yang tidak match route sebelumnya; kalau ditaruh di atas, POST/PUT/DELETE API
# jadi 405 (StaticFiles hanya support GET).
# SPA fallback: path non-API non-aset (mis. /sites, /databases dari vue-router
# history mode) diserve index.html, bukan 404.
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
