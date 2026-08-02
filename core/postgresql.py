"""Operasi PostgreSQL: create/drop DB + user.

Semua via subprocess argumen-list (tanpa shell=True). Nama DB/user divalidasi
di core/validate.py sebelum masuk sini.
Superuser akses: default peer auth (panel jalan sebagai postgres user), bisa dioverride
via env CCPANEL_PG_PASSWORD.
"""
from __future__ import annotations

import os
import subprocess

from . import validate

PG_HOST = os.environ.get("CCPANEL_PG_HOST", "localhost")
PG_PORT = os.environ.get("CCPANEL_PG_PORT", "5432")
PG_USER = os.environ.get("CCPANEL_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("CCPANEL_PG_PASSWORD", "")

class PostgresqlError(Exception):
    pass


def _psql(sql: str) -> None:
    env = os.environ.copy()
    if PG_PASSWORD:
        env["PGPASSWORD"] = PG_PASSWORD
    cmd = ["psql", f"--host={PG_HOST}", f"--port={PG_PORT}", f"--username={PG_USER}", "--command", sql]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise PostgresqlError(res.stderr.strip() or res.stdout.strip() or "psql failed")


def _check_host(host: str) -> None:
    """Host user PostgreSQL: 'localhost' | IP valid."""
    if host not in ("localhost", "127.0.0.1") and not validate.valid_ip(host):
        raise PostgresqlError("host tidak valid")


def create_db(db_name: str, db_user: str, password: str, host: str = "localhost") -> None:
    """Buat DB + user + GRANT. Password ditentukan pemanggil."""
    if not validate.valid_db_name(db_name) or not validate.valid_db_name(db_user):
        raise PostgresqlError("nama DB/user tidak valid")
    _check_host(host)
    _psql(
        f"CREATE DATABASE {db_name} ENCODING 'UTF8' LC_COLLATE 'en_US.UTF-8' LC_CTYPE 'en_US.UTF-8' TEMPLATE template0; "
        f"CREATE USER {db_user} WITH PASSWORD '{password}'; "
        f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"
    )


def reset_password(db_user: str, password: str, host: str = "localhost") -> None:
    """Ganti password user DB. Password ditentukan pemanggil."""
    if not validate.valid_db_name(db_user):
        raise PostgresqlError("nama user tidak valid")
    _check_host(host)
    _psql(f"ALTER USER {db_user} WITH PASSWORD '{password}';")


def drop_db(db_name: str, db_user: str, host: str = "localhost") -> None:
    if not validate.valid_db_name(db_name) or not validate.valid_db_name(db_user):
        raise PostgresqlError("nama DB/user tidak valid")
    _check_host(host)
    _psql(
        f"DROP DATABASE IF EXISTS {db_name}; "
        f"DROP USER IF EXISTS {db_user};"
    )


def test() -> None:
    _psql("SELECT 1;")