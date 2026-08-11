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
    docker,
    files,
    files_generic,
    ftp,
    logs,
    ports,
    projects,
    settings,
    sites,
    ssl,
    terminal_ws,
    trash,
    users,
    vhost,
)
