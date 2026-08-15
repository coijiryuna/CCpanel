"""API auth: login, me, dashboard."""
from __future__ import annotations

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.requests import Request

from pydantic import BaseModel

from .deps import _client_ip, _log, app, create_token, get_db, require_auth

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    token: str
    expires_in: int

@app.post("/api/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request) -> TokenResponse:
    ip = _client_ip(request)
    with get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (req.username,)
        ).fetchone()
    if row is None or not bcrypt.checkpw(req.password.encode(), row["password_hash"].encode()):
        _log(None, {"username": req.username, "ip": ip}, "login", "gagal")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    _log(None, {"username": req.username, "ip": ip}, "login", "sukses")
    return TokenResponse(token=create_token(req.username), expires_in=3600 * 12)

@app.get("/api/me")
def me(user: dict = Depends(require_auth)) -> dict:
    return {"username": user["username"], "role": user["role"]}

# ------------------------------------------------------------ dashboard
@app.get("/api/dashboard")
def dashboard(user: dict = Depends(require_auth)) -> dict:
    """Statistik panel. Admin: semua site. Client: site miliknya saja."""
    from core import monitor as monitor_ops

    with get_db() as conn:
        owner_id = None if user["role"] == "admin" else user["id"]
        return monitor_ops.dashboard(conn, owner_id)
