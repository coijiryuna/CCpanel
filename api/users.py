"""API users: CRUD user + reset password."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import bcrypt
from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import validate

from .deps import _log, app, dt_order, dt_params, dt_response, get_db, require_admin

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "client"

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: str

@app.get("/api/users", response_model=list[UserResponse] | dict)
def list_users(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "asc",
    user: dict = Depends(require_admin),
) -> list[UserResponse] | dict:
    start, length, draw = dt_params(start, length, draw)
    conds: list[str] = []
    args: list = []
    if search:
        s = f"%{search.strip()}%"
        conds.append("(username LIKE ? OR role LIKE ?)")
        args.extend([s, s])
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        filtered = conn.execute("SELECT COUNT(*) FROM users" + where, args).fetchone()[0]
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users" + where
            + dt_order(["id", "username", "role", "created_at"], order_col, order_dir)
            + (" LIMIT ? OFFSET ?" if length else ""),
            args + ([length, start] if length else []),
        ).fetchall()
    return dt_response([UserResponse(**dict(r)) for r in rows], start, length, total, filtered, draw)

@app.post("/api/users", response_model=UserResponse)
def create_user(req: UserCreate, user: dict = Depends(require_admin)) -> UserResponse:
    username = req.username.strip().lower()
    if not validate.valid_db_name(username):
        raise HTTPException(400, "Username tidak valid (a-z, 0-9, _, max 64)")
    if req.role not in ("admin", "client"):
        raise HTTPException(400, "Role harus admin atau client")
    if not req.password or len(req.password) < 6 or len(req.password) > 128:
        raise HTTPException(400, "Password 6-128 char")
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise HTTPException(409, "Username sudah ada")
        pw_hash = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (username, pw_hash, req.role, datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "user.create", f"{username} ({req.role})")
        row = conn.execute("SELECT id, username, role, created_at FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return UserResponse(**dict(row))

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(require_admin)) -> dict:
    """Hapus user. Site miliknya jadi tak bertuan (owner_id NULL)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "User tidak ada")
        if row["username"] == "admin":
            raise HTTPException(400, "Tidak bisa hapus admin utama")
        if user_id == user["id"]:
            raise HTTPException(400, "Tidak bisa hapus diri sendiri")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        _log(conn, user, "user.delete", row["username"])
    return {"ok": True}

@app.post("/api/users/{user_id}/reset-password")
def reset_user_password(user_id: int, user: dict = Depends(require_admin)) -> dict:
    """Reset password user client. Return password baru."""
    password = secrets.token_urlsafe(12)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "User tidak ada")
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
        _log(conn, user, "user.reset-password", row["username"])
    return {"ok": True, "password": password}
