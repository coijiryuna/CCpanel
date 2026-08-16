"""API project standalone: node/go/python/docker TANPA domain (backend
localhost:port), opsional bisa dikaitkan domain langsung (vhost proxy nginx).

Berbeda dari app per-site (api/apps.py) yang butuh site/domain. Project
standalone hidup di PROJECT_ROOT/<name>, unit systemd `ccpanel-proj-<name>`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi import Depends, HTTPException
from fastapi.requests import Request
from pydantic import BaseModel

from core import apps as apps_ops
from core import nginx as nginx_ops
from core import siteconfig as siteconfig_ops
from core import validate

from .deps import _log, app, dt_order, dt_params, dt_response, db_conn, require_auth

PROJECT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ProjectCreate(BaseModel):
    name: str
    app_type: str
    port: int
    entry: str | None = None
    run_opt: str | None = None
    user: str | None = None
    node_version: str | None = None
    go_version: str | None = None
    pm2: bool = False
    remark: str | None = None
    domain: str | None = None
    root_path: str | None = None  # optional: pakai folder existing


class ProjectUpdate(BaseModel):
    app_type: str | None = None
    port: int | None = None
    entry: str | None = None
    run_opt: str | None = None
    user: str | None = None
    node_version: str | None = None
    go_version: str | None = None
    pm2: bool | None = None
    remark: str | None = None
    root_path: str | None = None  # optional: pindah ke folder existing


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


def _validate_fields(app_type: str, port: int, node_version: str | None = None, go_version: str | None = None) -> None:
    if app_type not in apps_ops.APP_TYPES:
        raise HTTPException(400, f"Tipe aplikasi tidak valid. Pilihan: {', '.join(apps_ops.APP_TYPES)}")
    if not 1 <= port <= 65535:
        raise HTTPException(400, "Port tidak valid (1-65535)")
    if node_version and node_version not in apps_ops.NODE_VERSIONS:
        raise HTTPException(400, f"Versi node tidak valid. Pilihan: {', '.join(apps_ops.NODE_VERSIONS)}")
    if go_version and go_version not in apps_ops.GO_VERSIONS:
        raise HTTPException(400, f"Versi Go tidak valid. Pilihan: {', '.join(apps_ops.GO_VERSIONS)}")


@app.get("/api/projects", response_model=list[dict] | dict)
def list_projects(
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    search: str | None = None,
    order_col: str | None = None,
    order_dir: str = "asc",
    user: dict = Depends(require_auth),
) -> list[dict] | dict:
    start, length, draw = dt_params(start, length, draw)
    conds: list[str] = []
    args: list = []
    if user["role"] != "admin":
        conds.append("owner_id = ?")
        args.append(user["id"])
    if search:
        s = f"%{search.strip()}%"
        conds.append("(name LIKE ? OR app_type LIKE ? OR remark LIKE ?)")
        args.extend([s, s, s])
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with db_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM projects"
            + (f" WHERE owner_id = ?" if user["role"] != "admin" else ""),
            ([user["id"]] if user["role"] != "admin" else []),
        ).fetchone()[0]
        filtered = conn.execute("SELECT COUNT(*) FROM projects" + where, args).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM projects" + where
            + dt_order(["id", "name", "app_type", "port", "created_at"], order_col, order_dir)
            + (" LIMIT ? OFFSET ?" if length else ""),
            args + ([length, start] if length else []),
        ).fetchall()
    return dt_response([_project_row(conn, r) for r in rows], start, length, total, filtered, draw)


@app.post("/api/projects", response_model=dict)
def create_project(req: ProjectCreate, user: dict = Depends(require_auth)) -> dict:
    name = (req.name or "").strip()
    if not PROJECT_NAME_RE.fullmatch(name):
        raise HTTPException(400, "Nama project hanya huruf/angka/-/_ (max 64)")
    _validate_fields(req.app_type, req.port, req.node_version, req.go_version)
    entry = (req.entry or apps_ops.DEFAULT_ENTRY[req.app_type]).strip()
    run_user = (req.user or apps_ops.DEFAULT_USER).strip() or apps_ops.DEFAULT_USER
    run_opt = (req.run_opt or "").strip()
    node_version = (req.node_version or "").strip()
    go_version = (req.go_version or "").strip()
    remark = (req.remark or "").strip()
    domain = (req.domain or "").strip().lower()
    if domain and not validate.valid_domain(domain):
        raise HTTPException(400, f"Domain tidak valid: {domain}")

    # resolve root_path: user-provided or default PROJECT_ROOT/<name>
    if req.root_path:
        root = Path(req.root_path).resolve()
        if not root.exists():
            raise HTTPException(400, f"Folder root_path tidak ada: {root}")
    else:
        root = apps_ops.project_root(name)
    # auto-detect entry dari package.json / app.py kalau kosong
    entry = apps_ops.resolve_entry(req.app_type, root, entry)

    with db_conn() as conn:
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
            if req.root_path:
                # user-provided folder: siapkan deps, lalu tulis unit systemd
                if req.app_type not in apps_ops.APP_TYPES:
                    raise HTTPException(400, f"app_type tidak valid. Pilihan: {', '.join(apps_ops.APP_TYPES)}")
                if not 1 <= req.port <= 65535:
                    raise HTTPException(400, f"Port tidak valid: {req.port}")
                if req.app_type == "docker":
                    if not (root / "docker-compose.yml").exists():
                        raise HTTPException(400, f"docker-compose.yml tidak ada di {root}")
                apps_ops._prepare_project(req.app_type, root, run_user, node_version)
                apps_ops._do_create(
                    apps_ops._standalone_unit_path(name), name, root, req.app_type, req.port, entry,
                    run_user, run_opt, req.pm2, name, node_version, go_version,
                )
                final_root = root
            else:
                final_root = apps_ops.create_standalone(
                    name, req.app_type, req.port, entry,
                    user=run_user, run_opt=run_opt, pm2=req.pm2, node_version=node_version, go_version=go_version,
                )
            if domain:
                nginx_ops.project_proxy_enable(domain, req.port)
        except (apps_ops.AppError, nginx_ops.NginxError) as e:
            raise HTTPException(500, str(e)) from e
        cur = conn.execute(
            "INSERT INTO projects (name, app_type, port, entry, root_path, run_opt, user, node_version, go_version, pm2, remark, domain, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, req.app_type, req.port, entry, str(final_root), run_opt, run_user,
             node_version, go_version, 1 if req.pm2 else 0, remark, domain,
             None if user["role"] == "admin" else user["id"],
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "project.create", f"{name}: {req.app_type} port {req.port}"
             + (f" domain {domain}" if domain else " (tanpa domain)"))
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _project_row(conn, row)


@app.put("/api/projects/{project_id}", response_model=dict)
def update_project(project_id: int, req: ProjectUpdate, user: dict = Depends(require_auth)) -> dict:
    with db_conn() as conn:
        row = _check_project(conn, project_id, user)
        app_type = (req.app_type or row["app_type"]).lower()
        port = req.port or row["port"]
        entry = (req.entry if req.entry is not None else row["entry"] or apps_ops.DEFAULT_ENTRY[app_type]).strip()
        run_opt = (req.run_opt if req.run_opt is not None else row["run_opt"] or "").strip()
        run_user = (req.user if req.user is not None else row["user"] or apps_ops.DEFAULT_USER).strip()
        node_version = (req.node_version if req.node_version is not None else row["node_version"] or "").strip()
        go_version = (req.go_version if req.go_version is not None else row["go_version"] or "").strip()
        pm2 = req.pm2 if req.pm2 is not None else bool(row["pm2"])
        remark = (req.remark if req.remark is not None else row["remark"] or "").strip()
        _validate_fields(app_type, port, node_version, go_version)
        
        # handle root_path change
        old_root = Path(row["root_path"]) if row["root_path"] else apps_ops.project_root(row["name"])
        new_root = old_root
        if req.root_path is not None:
            if req.root_path:
                new_root = Path(req.root_path).resolve()
                if not new_root.exists():
                    raise HTTPException(400, f"Folder root_path tidak ada: {new_root}")
            else:
                new_root = apps_ops.project_root(row["name"])
        # auto-detect entry kalau user kosongkan
        entry = apps_ops.resolve_entry(app_type, new_root, entry)
        
        try:
            apps_ops.remove_standalone(row["name"], row["app_type"])
            if req.root_path is not None and req.root_path:
                # user-provided folder: siapkan deps, lalu tulis unit systemd
                if app_type not in apps_ops.APP_TYPES:
                    raise HTTPException(400, f"app_type tidak valid. Pilihan: {', '.join(apps_ops.APP_TYPES)}")
                if not 1 <= port <= 65535:
                    raise HTTPException(400, f"Port tidak valid: {port}")
                if app_type == "docker":
                    if not (new_root / "docker-compose.yml").exists():
                        raise HTTPException(400, f"docker-compose.yml tidak ada di {new_root}")
                apps_ops._prepare_project(app_type, new_root, run_user, node_version)
                apps_ops._do_create(
                    apps_ops._standalone_unit_path(row["name"]), row["name"], new_root, app_type, port, entry,
                    run_user, run_opt, pm2, row["name"], node_version, go_version,
                )
            else:
                new_root = apps_ops.create_standalone(
                    row["name"], app_type, port, entry,
                    user=run_user, run_opt=run_opt, pm2=pm2, node_version=node_version, go_version=go_version,
                )
            # domain proxy: kalau aktif dan port berubah, tulis ulang vhost
            if row["domain"] and row["port"] != port:
                nginx_ops.project_proxy_disable(row["domain"])
                nginx_ops.project_proxy_enable(row["domain"], port)
        except (apps_ops.AppError, nginx_ops.NginxError) as e:
            raise HTTPException(500, str(e)) from e
        conn.execute(
            "UPDATE projects SET app_type=?, port=?, entry=?, run_opt=?, user=?, node_version=?, go_version=?, pm2=?, remark=?, root_path=? WHERE id=?",
            (app_type, port, entry, run_opt, run_user, node_version, go_version, 1 if pm2 else 0,
             remark, str(new_root), project_id),
        )
        _log(conn, user, "project.update", f"{row['name']}: {app_type} port {port}")
        row2 = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project_row(conn, row2)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, user: dict = Depends(require_auth)) -> dict:
    with db_conn() as conn:
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
    with db_conn() as conn:
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
    with db_conn() as conn:
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
    with db_conn() as conn:
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
    with db_conn() as conn:
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

# ------------------------------------------- fitur web project berdomain

def _project_vhost(row) -> Path:
    """Vhost proxy project. Berdomain saja — tanpa domain tidak ada vhost."""
    if not row["domain"]:
        raise HTTPException(400, "Project belum punya domain — pasang domain dulu")
    vh = nginx_ops.project_vhost_path(row["domain"])
    if not vh.exists():
        raise HTTPException(500, f"vhost {vh} tidak ada")
    return vh

@app.get("/api/projects/{project_id}/webconfig")
def get_project_webconfig(project_id: int, user: dict = Depends(require_auth)) -> dict:
    """State fitur web project berdomain: rewrite, anti-XSS, access log, vhost."""
    with db_conn() as conn:
        row = _check_project(conn, project_id, user)
        vh = _project_vhost(row)
        feats = siteconfig_ops.state(row["domain"])
    return {
        "domain": row["domain"],
        "vhost_path": str(vh),
        "vhost_content": vh.read_text(encoding="utf-8"),
        "rewrite_rules": feats["rewrite_rules"],
        "xss_enabled": feats["xss_enabled"],
        "accesslog_enabled": feats["accesslog_enabled"],
    }

@app.put("/api/projects/{project_id}/webconfig")
async def put_project_webconfig(project_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Simpan fitur web project berdomain. Test + reload. Rollback kalau gagal."""
    import json

    try:
        body = json.loads(await req.body() or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None

    with db_conn() as conn:
        row = _check_project(conn, project_id, user)
        vh = _project_vhost(row)
        domain = row["domain"]
        backup = vh.read_text(encoding="utf-8")
        try:
            # vhost content dulu — fitur sisip include ke file ini
            if "vhost_content" in body:
                vh.write_text(body["vhost_content"])
            if "rewrite_rules" in body:
                siteconfig_ops.set_rewrite(domain, body.get("rewrite_rules", ""), vh, domain)
            if "xss_enabled" in body:
                siteconfig_ops.set_xss(domain, bool(body["xss_enabled"]), vh, domain)
            if "accesslog_enabled" in body:
                siteconfig_ops.set_accesslog(domain, bool(body["accesslog_enabled"]), vh, domain)
            nginx_ops.nginx_test()
        except (nginx_ops.NginxError, siteconfig_ops.Error) as e:
            vh.write_text(backup)
            raise HTTPException(400, str(e)) from e
        _log(conn, user, "project.webconfig", f"{row['name']}: {domain}")
    nginx_ops.nginx_reload()
    return {"ok": True}


# ------------------------------------------- compose + env project docker

def _project_compose_paths(row) -> tuple[Path, Path]:
    """(file_compose, file_env) project docker. Deteksi compose.yaml juga."""
    root = Path(row["root_path"]) if row["root_path"] else apps_ops.project_root(row["name"])
    compose = None
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yaml", "compose.yml"):
        cand = root / name
        if cand.exists():
            compose = cand
            break
    if compose is None:
        raise HTTPException(400, f"File compose tidak ada di {root} (docker-compose.yml / compose.yaml)")
    return compose, root / ".env"


@app.get("/api/projects/{project_id}/compose")
def get_project_compose(project_id: int, user: dict = Depends(require_auth)) -> dict:
    """Baca docker-compose.yml + .env project docker. 400 kalau bukan docker."""
    with db_conn() as conn:
        row = _check_project(conn, project_id, user)
        if row["app_type"] != "docker":
            raise HTTPException(400, "Fitur ini khusus project docker (app_type=docker)")
        compose, envf = _project_compose_paths(row)
    return {
        "compose_path": str(compose),
        "compose_content": compose.read_text(encoding="utf-8"),
        "env_path": str(envf),
        "env_content": envf.read_text(encoding="utf-8") if envf.exists() else "",
    }


@app.put("/api/projects/{project_id}/compose")
async def put_project_compose(project_id: int, req: Request, user: dict = Depends(require_auth)) -> dict:
    """Simpan docker-compose.yml + .env. YAML divalidasi; compose config kalau
    docker jalan; rollback kalau gagal. Tanpa restart — compose up manual."""
    import json

    try:
        body = json.loads(await req.body() or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "Body bukan JSON valid") from None

    with db_conn() as conn:
        row = _check_project(conn, project_id, user)
        if row["app_type"] != "docker":
            raise HTTPException(400, "Fitur ini khusus project docker (app_type=docker)")
        compose, envf = _project_compose_paths(row)
        backup_c = compose.read_text(encoding="utf-8") if compose.exists() else ""
        backup_e = envf.read_text(encoding="utf-8") if envf.exists() else ""
        try:
            if "compose_content" in body:
                content = body["compose_content"]
                if isinstance(content, str):
                    yaml.safe_load(content)  # ValueError/YAMLError → 400
                compose.write_text(content)
            if "env_content" in body:
                envf.write_text(body["env_content"])
            # validasi compose config kalau docker daemon hidup (skip kalau error)
            try:
                apps_ops._run([apps_ops.DOCKER_BIN, "compose", "-f", str(compose), "config", "--quiet"])
            except apps_ops.AppError:
                pass
        except (yaml.YAMLError, ValueError, OSError) as e:
            compose.write_text(backup_c)
            if envf.exists():
                envf.write_text(backup_e)
            raise HTTPException(400, f"compose tidak valid: {e}") from e
        _log(conn, user, "project.compose", f"{row['name']}: {compose.name}")
    return {"ok": True}
