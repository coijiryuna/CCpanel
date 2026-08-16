"""Infra bersama: app FastAPI, DB, auth, helper akses lintas modul.

Modul route di api/ import dari sini. Tidak ada circular import:
deps -> core, api/* -> deps, server.py -> deps + api/*.
"""
from __future__ import annotations

import ipaddress
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

import bcrypt
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.requests import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core import apps as apps_ops
from core import webserver as webserver_ops

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

JWT_SECRET = os.environ.get("PANEL_JWT_SECRET") or secrets.token_hex(32)
JWT_EXPIRES_HOURS = 12

app = FastAPI(title="CCPanel", docs_url=None, redoc_url=None)
bearer = HTTPBearer(auto_error=False)

from contextlib import closing, contextmanager

# ------------------------------------------------------------------ database
def _data_dir() -> Path:
    return Path(os.environ.get("CCPANEL_DATA_DIR", BASE_DIR / "data"))

def _db_path() -> Path:
    return _data_dir() / "ccpanel.db"

def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def db_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()

# ------------------------------------------------------- DataTables helper
def dt_response(
    rows: list,
    start: int = 0,
    length: int = 0,
    total: int | None = None,
    filtered: int | None = None,
    draw: int = 0,
) -> list | dict:
    """Bungkus baris jadi format DataTables server-side.

    rows HARUS sudah halaman yang benar (SQL LIMIT/OFFSET atau slice manual di
    caller). Kalau length > 0 → envelope {draw, recordsTotal, recordsFiltered,
    data}; kalau tidak → array polos (backward compatible).
    """
    if length > 0:
        return {
            "draw": draw,
            "recordsTotal": total if total is not None else len(rows),
            "recordsFiltered": filtered if filtered is not None else len(rows),
            "data": rows,
        }
    return rows

def dt_params(start: int = 0, length: int = 0, draw: int = 0) -> tuple[int, int, int]:
    """Batas aman: start >= 0, length 0..500. Echo draw balik (anti XSS/injection)."""
    return max(0, start), max(0, min(length, 500)), max(0, draw)

def dt_order(columns: list[str], order_col: str | None = None, order_dir: str = "asc") -> str:
    """Klausa ORDER BY aman: kolom cuma dari whitelist, arah cuma asc/desc.

    order_col bisa '0' (index kolom DataTables) atau nama kolom. Default 'id'.
    """
    col = (order_col or "").strip().lower()
    if col.isdigit():
        idx = int(col)
        col = columns[idx] if 0 <= idx < len(columns) else "id"
    if col not in columns:
        col = "id"
    return f" ORDER BY {col} {'DESC' if (order_dir or '').strip().lower() == 'desc' else 'ASC'}"

def init_db() -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'client',
                created_at    TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sites (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                domain     TEXT UNIQUE NOT NULL,
                root_path  TEXT NOT NULL,
                site_dir   TEXT NOT NULL DEFAULT '',
                running_dir TEXT NOT NULL DEFAULT '',
                vhost_path TEXT NOT NULL,
                enabled    INTEGER NOT NULL DEFAULT 1,
                waf_enabled INTEGER NOT NULL DEFAULT 0,
                hotlink_enabled INTEGER NOT NULL DEFAULT 0,
                owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                description TEXT NOT NULL DEFAULT '',
                category   TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dbs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id    INTEGER REFERENCES sites(id) ON DELETE SET NULL,
                db_name    TEXT UNIQUE NOT NULL,
                db_user    TEXT NOT NULL,
                db_pass    TEXT NOT NULL,
                db_host    TEXT NOT NULL DEFAULT 'localhost',
                owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                user       TEXT NOT NULL,
                action     TEXT NOT NULL,
                detail     TEXT NOT NULL DEFAULT '',
                ip         TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS ftp_accounts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id    INTEGER REFERENCES sites(id) ON DELETE CASCADE,
                username   TEXT UNIQUE NOT NULL,
                password   TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS site_apps (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id    INTEGER UNIQUE REFERENCES sites(id) ON DELETE CASCADE,
                app_type   TEXT NOT NULL,
                port       INTEGER NOT NULL,
                entry      TEXT NOT NULL DEFAULT '',
                subpath    TEXT NOT NULL DEFAULT '',
                name       TEXT NOT NULL DEFAULT '',
                run_opt    TEXT NOT NULL DEFAULT '',
                user       TEXT NOT NULL DEFAULT 'www',
                node_version TEXT NOT NULL DEFAULT '',
                pm2        INTEGER NOT NULL DEFAULT 0,
                remark     TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS site_domains (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id INTEGER REFERENCES sites(id) ON DELETE CASCADE,
                domain  TEXT NOT NULL,
                UNIQUE(site_id, domain)
            );
            CREATE TABLE IF NOT EXISTS projects (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT UNIQUE NOT NULL,
                app_type   TEXT NOT NULL,
                port       INTEGER NOT NULL,
                entry      TEXT NOT NULL DEFAULT '',
                root_path  TEXT NOT NULL DEFAULT '',
                run_opt    TEXT NOT NULL DEFAULT '',
                user       TEXT NOT NULL DEFAULT 'www',
                node_version TEXT NOT NULL DEFAULT '',
                pm2        INTEGER NOT NULL DEFAULT 0,
                remark     TEXT NOT NULL DEFAULT '',
                domain     TEXT NOT NULL DEFAULT '',
                owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                schedule   TEXT NOT NULL,
                command    TEXT NOT NULL,
                owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS docker_domains (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                container   TEXT NOT NULL,
                domain      TEXT NOT NULL,
                port        INTEGER NOT NULL,
                owner_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at  TEXT NOT NULL,
                UNIQUE(domain)
            );
            """
        )
        # migrasi: DB lama belum punya kolom baru
        ucols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "role" not in ucols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'client'")
            conn.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")
        scols = [r[1] for r in conn.execute("PRAGMA table_info(sites)").fetchall()]
        if "waf_enabled" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN waf_enabled INTEGER NOT NULL DEFAULT 0")
        if "owner_id" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        if "webserver" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN webserver TEXT NOT NULL DEFAULT 'nginx'")
        if "php_version" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN php_version TEXT NOT NULL DEFAULT 'static'")
        if "project_type" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN project_type TEXT NOT NULL DEFAULT 'static'")
        if "port" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN port INTEGER NOT NULL DEFAULT 0")
        if "proxy_enabled" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN proxy_enabled INTEGER NOT NULL DEFAULT 0")
        if "hotlink_enabled" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN hotlink_enabled INTEGER NOT NULL DEFAULT 0")
        if "description" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if "category" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN category TEXT NOT NULL DEFAULT ''")
        if "site_dir" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN site_dir TEXT NOT NULL DEFAULT ''")
        if "running_dir" not in scols:
            conn.execute("ALTER TABLE sites ADD COLUMN running_dir TEXT NOT NULL DEFAULT ''")
        dcols = [r[1] for r in conn.execute("PRAGMA table_info(dbs)").fetchall()]
        if "owner_id" not in dcols:
            conn.execute("ALTER TABLE dbs ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        if "db_type" not in dcols:
            conn.execute("ALTER TABLE dbs ADD COLUMN db_type TEXT NOT NULL DEFAULT 'mysql'")
        acols = [r[1] for r in conn.execute("PRAGMA table_info(site_apps)").fetchall()]
        if "name" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "run_opt" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN run_opt TEXT NOT NULL DEFAULT ''")
        if "user" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN user TEXT NOT NULL DEFAULT 'www'")
        if "node_version" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN node_version TEXT NOT NULL DEFAULT ''")
        if "pm2" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN pm2 INTEGER NOT NULL DEFAULT 0")
        if "remark" not in acols:
            conn.execute("ALTER TABLE site_apps ADD COLUMN remark TEXT NOT NULL DEFAULT ''")
        pcols = [r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()]
        if "domain" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN domain TEXT NOT NULL DEFAULT ''")
        if "owner_id" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN owner_id INTEGER REFERENCES users(id)")
        if "root_path" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN root_path TEXT NOT NULL DEFAULT ''")
        if "run_opt" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN run_opt TEXT NOT NULL DEFAULT ''")
        if "node_version" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN node_version TEXT NOT NULL DEFAULT ''")
        if "go_version" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN go_version TEXT NOT NULL DEFAULT ''")
        if "pm2" not in pcols:
            conn.execute("ALTER TABLE projects ADD COLUMN pm2 INTEGER NOT NULL DEFAULT 0")
        jcols = [r[1] for r in conn.execute("PRAGMA table_info(cron_jobs)").fetchall()]
        if "kind" not in jcols:
            conn.execute("ALTER TABLE cron_jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'command'")
        lcols = [r[1] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()]
        if "ip" not in lcols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN ip TEXT NOT NULL DEFAULT ''")
        seed_admin(conn)

def _log(conn: sqlite3.Connection | None, user: dict | str, action: str, detail: str = "") -> None:
    """Catat aksi ke audit_log. user boleh dict (dari require_auth) atau str polos."""
    if isinstance(user, dict):
        username = user["username"]
        ip = user.get("ip", "")
    else:
        username = user
        ip = ""
    row = (datetime.now(timezone.utc).isoformat(), username, action, detail, ip)
    if conn is not None:
        conn.execute("INSERT INTO audit_log (ts, user, action, detail, ip) VALUES (?, ?, ?, ?, ?)", row)
    else:
        with db_conn() as conn2:
            conn2.execute("INSERT INTO audit_log (ts, user, action, detail, ip) VALUES (?, ?, ?, ?, ?)", row)

def seed_admin(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        return
    password = os.environ.get("PANEL_PASSWORD")
    generated = False
    if not password:
        password = secrets.token_urlsafe(18)
        generated = True
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
        ("admin", pw_hash, datetime.now(timezone.utc).isoformat()),
    )
    if generated:
        # Wajib kuat; kalau tidak set env PANEL_PASSWORD, print sekali lalu keluar.
        print(f":: PANEL_PASSWORD belum diset. Generated: {password}")
        print(":: Set env PANEL_PASSWORD (kuat) lalu restart — password ini hanya ditampilkan sekali.")

# ---------------------------------------------------------------------- auth
def create_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(hours=JWT_EXPIRES_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _get_user(username: str) -> sqlite3.Row | None:
    with db_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

def _is_valid_ip(addr: str) -> bool:
    """Cek string adalah IP v4/v6 valid. Tolak spoof garbage seperti 'unknown'."""
    try:
        ipaddress.ip_address(addr.strip())
        return True
    except ValueError:
        return False


def _client_ip(request: Request) -> str:
    """IP asli client, prioritas: X-Real-IP → X-Forwarded-For (IP pertama valid) → socket.

    Catatan keamanan: header bisa dipalsukan kalau client akses langsung tanpa
    proxy. Di belakang nginx, pastikan nginx TIMPA header ini:
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    """
    real = request.headers.get("x-real-ip")
    if real and _is_valid_ip(real):
        return real.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        for part in xff.split(","):
            part = part.strip()
            if part and _is_valid_ip(part):
                return part
    return request.client.host if request.client else ""


def require_auth(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    """Return row user (dict) dari token. Raise 401 kalau token invalid/user hilang."""
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing token")
    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    row = _get_user(payload["sub"])
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User tidak ada")
    user = dict(row)
    user["ip"] = _client_ip(request)
    return user

def require_admin(user: dict = Depends(require_auth)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Khusus admin")
    return user

# ------------------------------------------------- helper akses lintas modul
def check_site_access(conn: sqlite3.Connection, site_id: int, user: dict) -> sqlite3.Row:
    """Ambil row site + cek akses: admin bebas, client hanya site miliknya."""
    row = conn.execute("SELECT * FROM sites WHERE id = ?", (site_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Site tidak ada")
    if user["role"] != "admin" and row["owner_id"] != user["id"]:
        raise HTTPException(403, "Bukan site Anda")
    return row

def check_db_access(conn: sqlite3.Connection, db_id: int, user: dict) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM dbs WHERE id = ?", (db_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "DB tidak ada")
    if user["role"] != "admin" and row["owner_id"] != user["id"]:
        raise HTTPException(403, "Bukan DB Anda")
    return row

def app_state(domain: str, root: str, app_type: str) -> str:
    try:
        return apps_ops.app_status(domain, Path(root), app_type)["state"]
    except apps_ops.AppError:
        return "error"

def check_domain_access(conn: sqlite3.Connection, site_id: int, user: dict) -> sqlite3.Row:
    """Cek akses site (untuk operasi domain/port). Sama dengan check_site_access."""
    return check_site_access(conn, site_id, user)

def validate_subpath(subpath: str) -> str:
    """Subpath: `/app1` — wajib diawali `/`, huruf/angka/-/_, tanpa `//`."""
    if not re.fullmatch(r"/[a-zA-Z0-9_-]+", subpath):
        raise HTTPException(400, "Subpath harus `/nama` (huruf/angka/-/_)")
    return subpath
