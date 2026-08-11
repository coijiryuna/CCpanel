"""CCPanel — hosting control panel backend.

Struktur:
  server.py   — startup + mount static (SPA). TIPIS.
  api/        — route per modul (auth, sites, apps, dbs, ...). Satu file per grup API.
  core/       — operasi sistem (nginx, php, database, cert, ...).

Jalankan: uvicorn server:app --host 127.0.0.1 --port 8888
"""
from __future__ import annotations

import os

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# register semua route API (import = register ke app via decorator)
from api import deps
from api import __init__ as _routes  # noqa: F401
from api.deps import STATIC_DIR, app, init_db
from core import database as database_ops
from core import webserver as webserver_ops

init_db()

# engine web server aktif: env override (testing), kalau tidak dari DB settings
if not os.environ.get("CCPANEL_WEBSERVER"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'webserver'").fetchone()
    if row:
        webserver_ops.set_active(row["value"])

# mode web server (single/multi): env override (testing), kalau tidak dari DB
if not os.environ.get("CCPANEL_WEBSERVER_MODE"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'webserver_mode'").fetchone()
    if row and row["value"] in webserver_ops.MODES:
        webserver_ops.set_mode(row["value"])

# engine database aktif: env override (testing), kalau tidak dari DB settings
if not os.environ.get("CCPANEL_DATABASE"):
    with deps.get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'database'").fetchone()
    if row:
        database_ops.set_active(row["value"])

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
