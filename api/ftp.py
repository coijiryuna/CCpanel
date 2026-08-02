"""API FTP: CRUD akun FTP + reset password."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import ftp as ftp_ops

from .deps import _log, app, get_db, require_auth

class FtpCreate(BaseModel):
    username: str
    password: str | None = None
    site_id: int

class FtpResponse(BaseModel):
    id: int
    site_id: int | None
    site_domain: str | None = None
    username: str
    password: str
    created_at: str

def _ftp_row(row, domain: str | None = None) -> FtpResponse:
    return FtpResponse(
        id=row["id"],
        site_id=row["site_id"],
        site_domain=domain,
        username=row["username"],
        password=row["password"],
        created_at=row["created_at"],
    )

def _check_ftp_access(conn, ftp_id: int, user: dict):
    row = conn.execute("SELECT * FROM ftp_accounts WHERE id = ?", (ftp_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Akun FTP tidak ada")
    if user["role"] == "admin":
        return row
    site = conn.execute("SELECT * FROM sites WHERE id = ?", (row["site_id"],)).fetchone()
    if site is None or site["owner_id"] != user["id"]:
        raise HTTPException(403, "Bukan akun Anda")
    return row

@app.get("/api/ftp", response_model=list[FtpResponse])
def list_ftp(user: dict = Depends(require_auth)) -> list[FtpResponse]:
    with get_db() as conn:
        if user["role"] == "admin":
            rows = conn.execute(
                "SELECT f.*, s.domain AS site_domain FROM ftp_accounts f "
                "LEFT JOIN sites s ON s.id = f.site_id ORDER BY f.id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT f.*, s.domain AS site_domain FROM ftp_accounts f "
                "JOIN sites s ON s.id = f.site_id "
                "WHERE s.owner_id = ? ORDER BY f.id", (user["id"],)
            ).fetchall()
    return [_ftp_row(r, r["site_domain"]) for r in rows]

@app.post("/api/ftp", response_model=FtpResponse)
def create_ftp(req: FtpCreate, user: dict = Depends(require_auth)) -> FtpResponse:
    with get_db() as conn:
        site = conn.execute("SELECT * FROM sites WHERE id = ?", (req.site_id,)).fetchone()
        if site is None:
            raise HTTPException(404, "Site tidak ada")
        if user["role"] != "admin" and site["owner_id"] != user["id"]:
            raise HTTPException(403, "Bukan site Anda")
        if conn.execute("SELECT 1 FROM ftp_accounts WHERE username = ?", (req.username.strip(),)).fetchone():
            raise HTTPException(409, "Akun FTP sudah ada")
        try:
            password = ftp_ops.create_account(req.username.strip(), req.password or "", req.site_id)
        except ftp_ops.FtpError as e:
            raise HTTPException(400, str(e)) from e
        cur = conn.execute(
            "INSERT INTO ftp_accounts (site_id, username, password, created_at) VALUES (?, ?, ?, ?)",
            (req.site_id, req.username.strip(), password, datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "ftp.create", f"{req.username.strip()} → {site['domain']}")
        row = conn.execute("SELECT * FROM ftp_accounts WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _ftp_row(row, site["domain"])

@app.post("/api/ftp/{ftp_id}/reset-password", response_model=FtpResponse)
def reset_ftp_password(ftp_id: int, user: dict = Depends(require_auth)) -> FtpResponse:
    with get_db() as conn:
        row = _check_ftp_access(conn, ftp_id, user)
        try:
            password = ftp_ops.reset_password(row["username"], "")
        except ftp_ops.FtpError as e:
            raise HTTPException(400, str(e)) from e
        conn.execute("UPDATE ftp_accounts SET password = ? WHERE id = ?", (password, ftp_id))
        _log(conn, user, "ftp.reset-password", row["username"])
        row = conn.execute("SELECT * FROM ftp_accounts WHERE id = ?", (ftp_id,)).fetchone()
    return _ftp_row(row)

@app.delete("/api/ftp/{ftp_id}")
def delete_ftp(ftp_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = _check_ftp_access(conn, ftp_id, user)
        try:
            ftp_ops.delete_account(row["username"])
        except ftp_ops.FtpError as e:
            raise HTTPException(400, str(e)) from e
        conn.execute("DELETE FROM ftp_accounts WHERE id = ?", (ftp_id,))
        _log(conn, user, "ftp.delete", row["username"])
    return {"ok": True}
