"""API logs + terminal."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import terminal as terminal_ops

from .deps import _log, app, get_db, require_admin

class LogEntry(BaseModel):
    id: int
    ts: str
    user: str
    action: str
    detail: str

@app.get("/api/logs", response_model=list[LogEntry])
def list_logs(limit: int = 100, user: dict = Depends(require_admin)) -> list[LogEntry]:
    """Audit trail: aksi admin terbaru dulu. Batasi jumlah biar tidak berat."""
    limit = max(1, min(limit, 500))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [LogEntry(**dict(r)) for r in rows]

class TerminalRequest(BaseModel):
    cmd: str

@app.post("/api/terminal/exec")
def terminal_exec(req: TerminalRequest, user: dict = Depends(require_admin)) -> dict:
    """Eksekusi perintah shell sebagai root. Akses penuh — hanya admin."""
    try:
        res = terminal_ops.exec_cmd(req.cmd)
    except terminal_ops.TerminalError as e:
        _log(None, user, "terminal.exec", f"DITOLAK: {req.cmd}")
        raise HTTPException(400, str(e)) from e
    _log(None, user, "terminal.exec", req.cmd)
    return res
