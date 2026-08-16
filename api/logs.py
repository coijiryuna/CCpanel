"""API logs + terminal."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import terminal as terminal_ops

from .deps import _log, app, dt_order, dt_params, dt_response, db_conn, require_admin

class LogEntry(BaseModel):
    id: int
    ts: str
    user: str
    action: str
    detail: str
    ip: str = ""

@app.get("/api/logs", response_model=list[LogEntry] | dict)
def list_logs(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "desc",
    limit: int = 100,
    user: dict = Depends(require_admin),
) -> list[LogEntry] | dict:
    """Audit trail: aksi admin terbaru dulu. DataTables: start+length; legacy: limit."""
    start, length, draw = dt_params(start, length, draw)
    conds: list[str] = []
    args: list = []
    if search:
        s = f"%{search.strip()}%"
        conds.append("(user LIKE ? OR action LIKE ? OR detail LIKE ? OR ip LIKE ?)")
        args.extend([s, s, s, s])
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with db_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        filtered = conn.execute("SELECT COUNT(*) FROM audit_log" + where, args).fetchone()[0]
        if length > 0:
            rows = conn.execute(
                "SELECT * FROM audit_log" + where
                + dt_order(["id", "ts", "user", "action", "detail", "ip"], order_col, order_dir)
                + " LIMIT ? OFFSET ?",
                args + [length, start],
            ).fetchall()
        else:
            # legacy: limit saja (tanpa offset) biar tetap backward compatible
            lim = max(1, min(limit, 500))
            rows = conn.execute(
                "SELECT * FROM audit_log" + where + " ORDER BY id DESC LIMIT ?",
                args + [lim],
            ).fetchall()
    return dt_response([LogEntry(**dict(r)) for r in rows], start, length, total, filtered, draw)

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
