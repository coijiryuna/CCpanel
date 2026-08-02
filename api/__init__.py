"""Route API per modul. Import di sini = daftar route yang diregister ke app.

Tambahkan modul baru di sini (bukan di server.py) — server.py hanya mount.
"""
from . import (  # noqa: F401  (import = register route ke app)
    apps,
    appstore,
    auth,
    backups,
    cron,
    dbs,
    files,
    files_generic,
    ftp,
    logs,
    projects,
    settings,
    sites,
    ssl,
    trash,
    users,
    vhost,
)
