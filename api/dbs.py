"""API databases: CRUD DB + reset password."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import database as database_ops
from core import validate

from .deps import _log, app, check_db_access, get_db, require_auth

class DbCreate(BaseModel):
    db_name: str
    db_user: str | None = None
    password: str | None = None
    host: str = "localhost"
    site_id: int | None = None
    db_type: str = "mysql"

class DbResponse(BaseModel):
    id: int
    db_name: str
    db_user: str
    db_pass: str
    db_host: str
    site_id: int | None
    db_type: str
    created_at: str

def _db_row(row) -> DbResponse:
    return DbResponse(
        id=row["id"],
        db_name=row["db_name"],
        db_user=row["db_user"],
        db_pass=row["db_pass"],
        db_host=row["db_host"],
        site_id=row["site_id"],
        db_type=row["db_type"] if "db_type" in row.keys() else "mysql",
        created_at=row["created_at"],
    )

@app.post("/api/dbs", response_model=DbResponse)
def create_db(req: DbCreate, user: dict = Depends(require_auth)) -> DbResponse:
    db_name = req.db_name.strip().lower()
    db_user = (req.db_user or db_name).strip().lower()
    if not validate.valid_db_name(db_name):
        raise HTTPException(400, "Nama DB tidak valid (a-z, 0-9, _, max 64)")
    if not validate.valid_db_name(db_user):
        raise HTTPException(400, "Username tidak valid (a-z, 0-9, _, max 64)")
    host = req.host.strip()
    if host not in ("localhost", "%") and not validate.valid_ip(host):
        raise HTTPException(400, "Permission tidak valid (localhost, %, atau IP)")
    db_type = req.db_type.strip().lower()
    if db_type not in database_ops.ENGINES:
        raise HTTPException(400, f"Database engine tidak didukung: {db_type}")
    password = (req.password or secrets.token_urlsafe(12)).strip()
    if not password or len(password) > 128:
        raise HTTPException(400, "Password tidak valid (1-128 char)")
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM dbs WHERE db_name = ?", (db_name,)).fetchone():
            raise HTTPException(409, "DB sudah ada")
        if req.site_id is not None:
            site = conn.execute("SELECT * FROM sites WHERE id = ?", (req.site_id,)).fetchone()
            if site is None:
                raise HTTPException(404, "Site tidak ada")
            # client hanya bisa buat DB untuk site miliknya; admin untuk site apa pun
            if user["role"] != "admin" and site["owner_id"] != user["id"]:
                raise HTTPException(403, "Bukan site Anda")
        eng = database_ops.for_engine(db_type)
        try:
            eng.create_db(db_name, db_user, password, host)
        except database_ops.DatabaseError as e:
            raise HTTPException(500, str(e)) from e
        owner_id = None if user["role"] == "admin" else user["id"]
        cur = conn.execute(
            "INSERT INTO dbs (site_id, db_name, db_user, db_pass, db_host, db_type, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.site_id, db_name, db_user, password, host, db_type, owner_id,
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "db.create", f"{db_name} ({db_user}@{host})")
        row = conn.execute("SELECT * FROM dbs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _db_row(row)

@app.get("/api/dbs", response_model=list[DbResponse])
def list_dbs(user: dict = Depends(require_auth)) -> list[DbResponse]:
    with get_db() as conn:
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM dbs ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dbs WHERE owner_id = ? ORDER BY id", (user["id"],)
            ).fetchall()
    return [_db_row(r) for r in rows]

@app.post("/api/dbs/{db_id}/reset-password", response_model=DbResponse)
def reset_db_password(db_id: int, user: dict = Depends(require_auth)) -> DbResponse:
    with get_db() as conn:
        row = check_db_access(conn, db_id, user)
        password = secrets.token_urlsafe(12)
        eng = database_ops.for_engine(row["db_type"])
        try:
            eng.reset_password(row["db_user"], password, row["db_host"])
        except database_ops.DatabaseError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE dbs SET db_pass = ? WHERE id = ?", (password, db_id))
        _log(conn, user, "db.reset-password", row["db_name"])
        row = conn.execute("SELECT * FROM dbs WHERE id = ?", (db_id,)).fetchone()
    return _db_row(row)

@app.delete("/api/dbs/{db_id}")
def delete_db(db_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = check_db_access(conn, db_id, user)
        eng = database_ops.for_engine(row["db_type"])
        try:
            eng.drop_db(row["db_name"], row["db_user"], row["db_host"])
        except database_ops.DatabaseError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("DELETE FROM dbs WHERE id = ?", (db_id,))
        _log(conn, user, "db.delete", row["db_name"])
    return {"ok": True}
