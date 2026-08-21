"""API Docker manager: container list/action/log + image list/import.

Read-only list + aksi container umum. Tidak ada DB state — semua dari
`docker` CLI langsung. Docker tidak terinstall → error 400 dengan pesan
"pasang via App Store" (bukan 500).
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.requests import Request

from pydantic import BaseModel

from core import docker as docker_ops
from core import nginx as nginx_ops
from core import validate

from .deps import _log, app, db_conn, require_auth


def _docker_err(e: docker_ops.DockerError) -> HTTPException:
    return HTTPException(400, str(e))


class PullImageReq(BaseModel):
    image: str


class CreateContainerReq(BaseModel):
    image: str
    name: str = ""
    port: str = ""
    env: str = ""
    restart: str = "no"
    volume: str = ""
    cmd: str = ""
    domain: str = ""


class ContainerDomainReq(BaseModel):
    domain: str
    port: int


@app.get("/api/docker/containers")
def docker_containers(all: bool = False, user: dict = Depends(require_auth)) -> dict:
    try:
        rows = docker_ops.containers(all_c=all)
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    # gabung domain yang terpasang
    with db_conn() as conn:
        dm = {r["container"]: {"domain": r["domain"], "port": r["port"]}
              for r in conn.execute("SELECT container, domain, port FROM docker_domains").fetchall()}
    for r in rows:
        d = dm.get(r["id"]) or dm.get(r["names"])
        r["domain"] = d["domain"] if d else ""
        r["domain_port"] = d["port"] if d else None
    return {"containers": rows, "available": True}


@app.get("/api/docker/images")
def docker_images(user: dict = Depends(require_auth)) -> dict:
    try:
        rows = docker_ops.images()
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    return {"images": rows}


@app.post("/api/docker/containers/{container_id}/action")
def docker_container_action(container_id: str, req: dict, user: dict = Depends(require_auth)) -> dict:
    action = (req.get("action") or "").strip()
    try:
        r = docker_ops.container_action(container_id, action)
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    with db_conn() as conn:
        _log(conn, user, f"docker.container.{action}", f"{container_id[:12]}")
        conn.commit()
    return r


@app.get("/api/docker/containers/{container_id}/log")
def docker_container_log(container_id: str, lines: int = 200, user: dict = Depends(require_auth)) -> dict:
    try:
        text = docker_ops.container_logs(container_id, lines)
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    return {"log": text}


@app.post("/api/docker/images/pull")
def docker_pull_image(req: PullImageReq, user: dict = Depends(require_auth)) -> dict:
    try:
        out = docker_ops.pull_image(req.image)
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    with db_conn() as conn:
        _log(conn, user, "docker.image.pull", req.image)
        conn.commit()
    return {"ok": True, "output": out}


@app.post("/api/docker/containers")
def docker_create_container(req: CreateContainerReq, user: dict = Depends(require_auth)) -> dict:
    try:
        cid = docker_ops.create_container(
            req.image, req.name, req.port, req.env, req.restart, req.volume, req.cmd
        )
    except docker_ops.DockerError as e:
        raise _docker_err(e) from e
    with db_conn() as conn:
        _log(conn, user, "docker.container.create", f"{req.name or req.image}")
    # domain opsional: proxy ke host port pertama (atau port eksplisit)
    if req.domain:
        host_port = req.port.split(",")[0].split(":")[0].strip()
        if not host_port.isdigit():
            raise HTTPException(
                400, "Domain butuh mapping port host:container (mis. 8080:80)")
        _attach_domain(cid or req.name, req.domain, int(host_port), user)
        conn.commit()
    return {"ok": True, "id": cid}


def _attach_domain(container: str, domain: str, port: int, user: dict) -> None:
    """Pasang domain → vhost proxy ke 127.0.0.1:<host port container>."""
    domain = (domain or "").strip().lower()
    if not validate.valid_domain(domain):
        raise HTTPException(400, f"Domain tidak valid: {domain}")
    if not 1 <= port <= 65535:
        raise HTTPException(400, f"Port tidak valid: {port}")
    with db_conn() as conn:
        if conn.execute("SELECT 1 FROM docker_domains WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai")
        if conn.execute("SELECT 1 FROM projects WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai project")
        if conn.execute("SELECT 1 FROM sites WHERE domain = ?", (domain,)).fetchone():
            raise HTTPException(409, f"Domain {domain} sudah dipakai site")
    try:
        nginx_ops.project_proxy_enable(domain, port)
    except nginx_ops.NginxError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO docker_domains (container, domain, port, owner_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (container, domain, port,
             None if user["role"] == "admin" else user["id"],
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "docker.domain-add", f"{domain} → {container}:{port}")
        conn.commit()


@app.post("/api/docker/containers/{container_id}/domain")
def docker_container_domain_add(container_id: str, req: ContainerDomainReq, user: dict = Depends(require_auth)) -> dict:
    """Pasang domain ke container yang sudah ada. Proxy ke host port."""
    _attach_domain(container_id, req.domain, req.port, user)
    return {"ok": True}


@app.delete("/api/docker/containers/{container_id}/domain")
def docker_container_domain_remove(container_id: str, user: dict = Depends(require_auth)) -> dict:
    """Lepas domain container. Hapus vhost proxy."""
    with db_conn() as conn:
        row = conn.execute(
            "SELECT domain FROM docker_domains WHERE container = ?", (container_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Container tidak punya domain")
        domain = row["domain"]
    try:
        nginx_ops.project_proxy_disable(domain)
    except nginx_ops.NginxError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM docker_domains WHERE container = ?", (container_id,))
        conn.commit()
        _log(conn, user, "docker.domain-remove", f"{container_id}: -{domain}")
    return {"ok": True}


MAX_IMPORT_SIZE = 512 * 1024 * 1024  # 512 MB — batas file tar image


@app.post("/api/docker/images/import")
async def docker_import_image(file: UploadFile = File(...), user: dict = Depends(require_auth)) -> dict:
    """Import image dari file tar lokal (hasil `docker save`). Stream ke temp,
    `docker load -i`, hapus temp. Size dicek saat stream (tak percaya header)."""
    name = (file.filename or "image.tar").replace("\\", "/").split("/")[-1]
    if not (name.endswith(".tar") or name.endswith(".tar.gz") or name.endswith(".tgz")):
        raise HTTPException(
            400, "File harus .tar / .tar.gz / .tgz (hasil docker save)")
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_IMPORT_SIZE:
                    raise HTTPException(
                        400, f"File > {MAX_IMPORT_SIZE // 1024 // 1024} MB — terlalu besar")
                tmp.write(chunk)
        try:
            out = docker_ops.load_image(str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Import gagal: {e}") from e
    with db_conn() as conn:
        _log(conn, user, "docker.image.import", name)
        conn.commit()
    return {"ok": True, "output": out}
