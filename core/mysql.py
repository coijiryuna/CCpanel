"""Operasi MySQL/MariaDB: create/drop DB + user.

Semua via subprocess argumen-list (tanpa shell=True). Nama DB/user divalidasi
di core/validate.py sebelum masuk sini — backtick aman karena charset whitelist.
Root akses: default socket auth (panel jalan sebagai root), bisa dioverride
via env CCPANEL_MYSQL_ROOT_PASSWORD.
"""
from __future__ import annotations

import os
import subprocess

from . import validate

MYSQL_HOST = os.environ.get("CCPANEL_MYSQL_HOST", "localhost")
MYSQL_ROOT_PASSWORD = os.environ.get("CCPANEL_MYSQL_ROOT_PASSWORD", "")


class MysqlError(Exception):
    pass


def _mysql(sql: str) -> None:
    cmd = ["mysql", f"--host={MYSQL_HOST}", "--user=root"]
    if MYSQL_ROOT_PASSWORD:
        cmd.append(f"--password={MYSQL_ROOT_PASSWORD}")
    cmd.append(f"--execute={sql}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise MysqlError(res.stderr.strip() or res.stdout.strip() or "mysql failed")


def _check_host(host: str) -> None:
    """Host user MySQL: 'localhost' | '%' | IPv4 valid."""
    if host not in ("localhost", "%") and not validate.valid_ip(host):
        raise MysqlError("host tidak valid")

def create_db(db_name: str, db_user: str, password: str, host: str = "localhost") -> None:
    """Buat DB + user@host + GRANT. Password ditentukan pemanggil."""
    if not validate.valid_db_name(db_name) or not validate.valid_db_name(db_user):
        raise MysqlError("nama DB/user tidak valid")
    _check_host(host)
    _mysql(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        f"CREATE USER IF NOT EXISTS '{db_user}'@'{host}' IDENTIFIED BY '{password}'; "
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{host}'; "
        "FLUSH PRIVILEGES;"
    )


def reset_password(db_user: str, password: str, host: str = "localhost") -> None:
    """Ganti password user DB. Password ditentukan pemanggil."""
    if not validate.valid_db_name(db_user):
        raise MysqlError("nama user tidak valid")
    _check_host(host)
    _mysql(
        f"ALTER USER '{db_user}'@'{host}' IDENTIFIED BY '{password}'; "
        "FLUSH PRIVILEGES;"
    )

def drop_db(db_name: str, db_user: str, host: str = "localhost") -> None:
    if not validate.valid_db_name(db_name) or not validate.valid_db_name(db_user):
        raise MysqlError("nama DB/user tidak valid")
    _check_host(host)
    _mysql(
        f"DROP DATABASE IF EXISTS `{db_name}`; "
        f"DROP USER IF EXISTS '{db_user}'@'{host}';"
    )
