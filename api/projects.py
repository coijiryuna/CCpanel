"""API project standalone: node/go/python/docker TANPA domain (backend
localhost:port), opsional bisa dikaitkan domain langsung (vhost proxy nginx).

Berbeda dari app per-site (api/apps.py) yang butuh site/domain. Project
standalone hidup di PROJECT_ROOT/<name>, unit systemd `ccpanel-proj-<name>`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from core import apps as apps_ops
from core import nginx as nginx_ops
from core import validate

from .deps import _log, app, get_db, require_auth

PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ProjectCreate(BaseModel):
    name: str
    app_type: str
    port: int
    entry: str | None = None
    run_opt: str | None = None
    user: str | None = None
    node_version: str | None = None
    pm2: bool = False
    remark: str | None = None
    domain: str | None = None


class ProjectUpdate(BaseModel):
    app_type: str | None = None
    port: int | None = None
    entry: str | None = None
    run_opt: str | None = None
    user: str | None = None
    node_version: str | None = None
    pm2: bool | None = None
    remark: str | None = None


def _project_row(conn, row) -> dict:
    st = apps_ops.standalone_status(row["name"], row["app_type"])
    return {
        "id": row["id"], "name": row["name"], "app_type": row["app_type"],
        "port": row["port"], "entry": row["entry"], "root_path": row["root_path"],
        "run_opt": row["run_opt"], "user": row["user"],
        "node_version": row["node_version"], "pm2": bool(row["pm2"]),
        "remark": row["remark"], "domain": row["domain"],
        "state": st["state"], "detail": st.get("detail", ""),
        "pid": st.get("pid"),
    }


def _check_project(conn, project_id: int, user: dict):
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project tidak ada")
    if user["role"] != "admin" and row["owner_id"] != user["id"]:
        raise HTTPException(403, "Bukan project Anda")
    return row


def _validate_fields(app_type: str, port: int, node_version: str | None = None) -> None:
    if app_type not in apps_ops.APP_TYPES:
        raise HTTPException(400, f"Tipe aplikasi tidak valid. Pilihan: {', '.join(apps_ops.APP_TYPES)}")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    if node_version and node_version not in apps_ops.NODE_VERSIONS:
        raise HTTPException(400, f"Versi node tidak valid. Pilihan: {', '.join(apps_ops.NODE_VERSIONS)}")


@app.get("/api/projects", response_model=list[dict])
def list_projects(user: dict = Depends(require_auth)) -> list[dict]:
    with get_db() as conn:
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM projects WHERE owner_id = ? ORDER BY id", (user["id"],)
            ).fetchall()
        return [_project_row(conn, r) for r in rows]


@app.post("/api/projects", response_model=dict)
def create_project(req: ProjectCreate, user: dict = Depends(require_auth)) -> dict:
    name = (req.name or "").strip()
    if not PROJECT_NAME_RE.fullmatch(name):
        raise HTTPException(400, "Nama project hanya huruf/angka/-/_ (max 64)")
    _validate_fields(req.app_type, req.port, req.node_version)
    entry = (req.entry or apps_ops.DEFAULT_ENTRY[req.app_type]).strip()
    run_user = (req.user or apps_ops.DEFAULT_USER).strip() or apps_ops.DEFAULT_USER
    run_opt = (req.run_opt or "").strip()
    node_version = (req.node_version or "").strip()
    remark = (req.remark or "").strip()
    domain = (req.domain or "").strip().lower()
    if domain and not validate.valid_domain(domain):
        raise HTTPException(400, f"Domain tidak valid: {domain}")

    with get_db() as conn:
        if conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone():
            raise HTTPException(409, f"Project {name} sudah ada")
        if domain:
            if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
                raise HTTPException(409, f"Domain {domain} sudah dipakai site")
            if conn.execute("SELECT 1 FROM projects WHERE domain = ?", (domain,)).fetchone():
                raise HTTPException(409, f"Domain {domain} sudah dipakai project lain")
            if conn.execute(
                "SELECT 1 FROM site_domains WHERE domain = ?", (domain,)
            ).fetchone():
                raise HTTPException(409, f"Domain {domain} sudah jadi alias site")
        try:
            root = apps_ops.create_standalone(
                name, req.app_type, req.port, entry,
                user=run_user, run_opt=run_opt, pm2=req.pm2, node_version=node_version,
            )
            if domain:
                nginx_ops.project_proxy_enable(domain, req.port)
        except (apps_ops.AppError, nginx_ops.NginxError) as e:
            raise HTTPException(500, str(e)) from e
        cur = conn.execute(
            "INSERT INTO projects (name, app_type, port, entry, root_path, run_opt, user, node_version, pm2, remark, domain, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, req.app_type, req.port, entry, str(root), run_opt, run_user,
             node_version, 1 if req.pm2 else 0, remark, domain,
             None if user["role"] == "admin" else user["id"],
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "project.create", f"{name}: {req.app_type} port {req.port}"
             + (f" domain {domain}" if domain else " (tanpa domain)"))
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _project_row(conn, row)


@app.put("/api/projects/{project_id}", response_model=dict)
def update_project(project_id: int, req: ProjectUpdate, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        app_type = (req.app_type or row["app_type"]).lower()
        port = req.port or row["port"]
        entry = (req.entry if req.entry is not None else row["entry"] or apps_ops.DEFAULT_ENTRY[app_type]).strip()
        run_opt = (req.run_opt if req.run_opt is not None else row["run_opt"] or "").strip()
        user = (req.user if req.user is not None else row["user"] or apps_ops.DEFAULT_USER).strip()
        node_version = (req.node_version if req.node_version is not None else row["node_version"] or "").strip()
        pm2 = req.pm2 if req.pm2 is not None else bool(row["pm2"])
        remark = (req.remark if req.remark is not None else row["remark"] or "").strip()
        _validate_fields(app_type, port, node_version)
        root = Path(row["root_path"]) if row["root_path"] else apps_ops.project_root(row["name"])
        try:
            apps_ops.remove_standalone(row["name"], row["app_type"])
            apps_ops.create_standalone(
                row["name"], app_type, port, entry,
                user=user, run_opt=run_opt, pm2=pm2, node_version=node_version,
            )
            # domain proxy: kalau aktif dan port berubah, tulis ulang vhost
            if row["domain"] and row["port"] != port:
                nginx_ops.project_proxy_disable(row["domain"])
                nginx_ops.project_proxy_enable(row["domain"], port)
        except (apps_ops.AppError, nginx_ops.NginxError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute(
            "UPDATE projects SET app_type=?, port=?, entry=?, run_opt=?, user=?, node_version=?, pm2=?, remark=? WHERE id=?",
            (app_type, port, entry, run_opt, user, node_version, 1 if pm2 else 0,
             remark, project_id),
        )
        _log(conn, user, "project.update", f"{row['name']}: {app_type} port {port}")
        row2 = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(conn, row2)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        try:
            apps_ops.remove_standalone(row["name"], row["app_type"])
            if row["domain"]:
                nginx_ops.project_proxy_disable(row["domain"])
        except (apps_ops.AppError, nginx_ops.NginxError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        _log(conn, user, "project.delete", row["name"])
    return {"ok": True}


@app.post("/api/projects/{project_id}/action")
def project_action(project_id: int, req: dict, user: dict = Depends(require_auth)) -> dict:
    action = (req.get("action") or "").strip()
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        try:
            apps_ops.standalone_action(row["name"], row["app_type"], action)
            st = apps_ops.standalone_status(row["name"], row["app_type"])
        except apps_ops.AppError as e:
            raise HTTPException(500, str(e)) from e
        _log(conn, user, f"project.{action}", row["name"])
    return {"ok": True, "state": st["state"], "detail": st.get("detail", ""), "pid": st.get("pid")}


@app.get("/api/projects/{project_id}/log")
def project_log(project_id: int, lines: int = 100, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        try:
            text = apps_ops.standalone_log_tail(row["name"], row["app_type"], lines)
        except apps_ops.AppError as e:
            raise HTTPException(500, str(e)) from e
    return {"log": text}


# ------------------------------------------------------------- domain (proxy)


class ProjectDomain(BaseModel):
    domain: str


@app.post("/api/projects/{project_id}/domain")
def attach_project_domain(project_id: int, req: ProjectDomain, user: dict = Depends(require_auth)) -> dict:
    domain = (req.domain or "").strip().lower()
    if not validate.valid_domain(domain):
        raise HTTPException(400, f"Domain tidak valid: {domain}")
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        if row["domain"]:
            raise HTTPException(409, f"Project sudah punya domain: {row['domain']} — lepas dulu")
        if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai site")
        if conn.execute("SELECT 1 FROM projects WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai project lain")
        if conn.execute("SELECT 1 FROM site_domains WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah jadi alias site")
        try:
            nginx_ops.project_proxy_enable(domain, row["port"])
        except nginx_ops.NginxError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE projects SET domain = ? WHERE id = ?", (domain, project_id))
        _log(conn, user, "project.domain", f"{row['name']}: +{domain} -> :{row['port']}")
        row2 = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(conn, row2)


@app.delete("/api/projects/{project_id}/domain")
def detach_project_domain(project_id: int, user: dict = Depends(require_auth)) -> dict:
    with get_db() as conn:
        row = _check_project(conn, project_id, user)
        if not row["domain"]:
            raise HTTPException(400, "Project tidak punya domain")
        try:
            nginx_ops.project_proxy_disable(row["domain"])
        except nginx_ops.NginxError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE projects SET domain = '' WHERE id = ?", (project_id,))
        _log(conn, user, "project.domain-remove", f"{row['name']}: -{row['domain']}")
        row2 = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(conn, row2)
