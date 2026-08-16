"""API cron: auto-renew SSL + cron job custom (tambah/hapus user)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import cron as cron_ops

from .deps import _log, app, db_conn, require_admin, require_auth

SCHEDULE_RE = re.compile(r"^(\*|[0-9]+)(\s+(\*|[0-9]+)){4}$")
KINDS = ("command", "script", "url")

class CronJobCreate(BaseModel):
    name: str
    schedule: str
    command: str
    kind: str = "command"

@app.get("/api/cron/status")
def cron_status(user: dict = Depends(require_admin)) -> dict:
    try:
        return cron_ops.status()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e

@app.post("/api/cron/install")
def cron_install(user: dict = Depends(require_admin)) -> dict:
    """Pasang auto-renew SSL: script + crontab root. Idempoten."""
    try:
        res = cron_ops.install()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "cron.install", res.get("script", ""))
    return res

@app.post("/api/cron/uninstall")
def cron_uninstall(user: dict = Depends(require_admin)) -> dict:
    """Hapus auto-renew SSL: crontab line + script. Idempoten."""
    try:
        res = cron_ops.uninstall()
    except cron_ops.CronError as e:
        raise HTTPException(500, str(e)) from e
    _log(None, user, "cron.uninstall", "")
    return res

# ----------------------------------------------------------------- custom jobs

def _job_row(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "schedule": row["schedule"],
        "command": row["command"], "kind": row["kind"], "created_at": row["created_at"],
    }

def _sync_all(conn) -> None:
    """Tulis ulang crontab dari isi tabel — hapus line yatim (job dihapus DB)."""
    rows = conn.execute("SELECT id, kind, schedule, command FROM cron_jobs ORDER BY id").fetchall()
    cron_ops.sync_custom([dict(r) for r in rows])

@app.get("/api/cron/jobs")
def list_cron_jobs(user: dict = Depends(require_auth)) -> list[dict]:
    """Daftar cron job custom. Admin lihat semua, client hanya punya sendiri."""
    with db_conn() as conn:
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM cron_jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cron_jobs WHERE owner_id = ? ORDER BY id DESC", (user["id"],)
            ).fetchall()
    return [_job_row(r) for r in rows]

@app.post("/api/cron/jobs", response_model=dict)
def create_cron_job(req: CronJobCreate, user: dict = Depends(require_auth)) -> dict:
    """Tambah cron job custom. Admin bebas, client dibatasi perintah berbahaya."""
    name = (req.name or "").strip()
    schedule = (req.schedule or "").strip()
    command = (req.command or "").strip()
    kind = (req.kind or "command").strip().lower()
    if kind not in KINDS:
        raise HTTPException(400, f"Jenis tidak valid. Pilihan: {', '.join(KINDS)}")
    if not name or len(name) > 64:
        raise HTTPException(400, "Nama wajib (max 64)")
    if not command:
        raise HTTPException(400, "Perintah/URL/script wajib")
    if len(command) > 1000:
        raise HTTPException(400, "Perintah terlalu panjang (max 1000)")
    if not SCHEDULE_RE.fullmatch(schedule):
        raise HTTPException(400, "Jadwal tidak valid. Contoh: 0 3 * * * (menit jam hari-bulan bulan hari-minggu)")
    if kind == "script":
        p = Path(command)
        if not p.is_absolute():
            raise HTTPException(400, "Path script harus absolut, contoh: /www/project/backup.sh")
        if not p.exists():
            raise HTTPException(400, f"Script tidak ada: {command}")
    if kind == "url":
        if not command.startswith(("http://", "https://")):
            raise HTTPException(400, "URL harus diawali http:// atau https://")
    if user["role"] != "admin":
        # client: jangan izinkan perintah berbahaya
        low = command.lower()
        banned = ("sudo", "su ", "rm -rf", ":(){:", "mkfs", "> /dev/sd", "/etc/", "/root/")
        if any(b in low for b in banned):
            raise HTTPException(403, "Perintah dilarang untuk user biasa")
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cron_jobs (name, schedule, command, kind, owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, schedule, command, kind,
             None if user["role"] == "admin" else user["id"],
             datetime.now(timezone.utc).isoformat()),
        )
        try:
            _sync_all(conn)
        except cron_ops.CronError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "cron.add", f"{name}: {kind} {schedule} {command}")
        conn.commit()
        row = conn.execute("SELECT * FROM cron_jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _job_row(row)

@app.delete("/api/cron/jobs/{job_id}")
def delete_cron_job(job_id: int, user: dict = Depends(require_auth)) -> dict:
    """Hapus cron job custom + line crontab-nya."""
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Cron job tidak ada")
        if user["role"] != "admin" and row["owner_id"] != user["id"]:
            raise HTTPException(403, "Bukan cron job Anda")
        conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        try:
            _sync_all(conn)
        except cron_ops.CronError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, "cron.remove", row["name"])
        conn.commit()
    return {"ok": True}
