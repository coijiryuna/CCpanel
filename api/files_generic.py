"""API file manager generik: list, upload, hapus, buat folder, rename, edit teks,
unzip/untar, chmod/chown, download (file / folder zip) untuk root path yang diizinkan.

Root path yang diizinkan:
- WWW_ROOT (default /www/wwwroot) — untuk file site umum
- PROJECT_ROOT (default /www/project) — untuk folder project standalone
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tarfile
import zipfile
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .deps import app, get_db, require_auth
from core import apps as apps_ops
from core import nginx as nginx_ops

MAX_TEXT_SIZE = 2 * 1024 * 1024  # 2 MB — batas baca/tulis file teks

class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int | None = None

class MkdirReq(BaseModel):
    path: str = ""
    name: str

class RenameReq(BaseModel):
    path: str
    new_name: str

class TextReq(BaseModel):
    path: str
    content: str

class ChmodReq(BaseModel):
    path: str
    mode: str

class ChownReq(BaseModel):
    path: str
    owner: str = ""  # "user", "user:group", atau ":group" — kosong = skip

NAME_RE = re.compile(r"^[^/\\\x00]{1,255}$")

# Root path yang diizinkan untuk file manager generik
ALLOWED_ROOTS = {
    "wwwroot": nginx_ops.WWW_ROOT,
    "project": apps_ops.PROJECT_ROOT,
}

def _get_allowed_root(root_key: str) -> Path:
    """Dapatkan root path yang diizinkan berdasarkan key."""
    if root_key not in ALLOWED_ROOTS:
        raise HTTPException(400, f"Root tidak diizinkan: {root_key}. Pilihan: {', '.join(ALLOWED_ROOTS.keys())}")
    root = ALLOWED_ROOTS[root_key]
    if not root.is_dir():
        raise HTTPException(404, f"Root path tidak ada: {root}")
    return root

def _resolve_within(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(400, "Path di luar root")
    return target

def _valid_name(name: str) -> str:
    """Nama entry: tanpa path separator, tanpa . / .. — aman untuk mkdir/rename."""
    if not NAME_RE.match(name) or name in (".", ".."):
        raise HTTPException(400, "Nama tidak valid")
    return name

@app.get("/api/files/{root_key}")
def list_files_generic(root_key: str, path: str = "", user: dict = Depends(require_auth)) -> list[FileEntry]:
    """List isi folder di root yang diizinkan (wwwroot/project)."""
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, path)
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")
    if target.is_file():
        raise HTTPException(400, "Bukan folder")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        entries.append(
            FileEntry(
                name=child.name,
                path=str(child.relative_to(root)),
                is_dir=child.is_dir(),
                size=child.stat().st_size if child.is_file() else None,
            )
        )
    return entries

@app.post("/api/files/{root_key}")
def upload_file_generic(
    root_key: str,
    path: str = "",
    file: UploadFile = File(...),
    user: dict = Depends(require_auth),
) -> dict:
    """Upload ke folder `path` di root yang diizinkan."""
    root = _get_allowed_root(root_key)
    folder = _resolve_within(root, path)
    folder.mkdir(parents=True, exist_ok=True)

    raw = (file.filename or "upload").replace("\\", "/")
    name = Path(raw).name
    if (
        not name
        or name in (".", "..")
        or raw != name
        or "/" in name
        or "\x00" in name
    ):
        raise HTTPException(400, "Nama file tidak valid")

    target = folder / name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"ok": True, "path": str(target.relative_to(root))}

@app.delete("/api/files/{root_key}")
def delete_file_generic(root_key: str, path: str, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, path)
    if target == root:
        raise HTTPException(400, "Tidak bisa hapus root")
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"ok": True}

@app.post("/api/files/{root_key}/mkdir")
def mkdir_file_generic(root_key: str, req: MkdirReq, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    parent = _resolve_within(root, req.path)
    if not parent.is_dir():
        raise HTTPException(404, "Folder induk tidak ada")
    target = parent / _valid_name(req.name)
    if target.exists():
        raise HTTPException(409, "Sudah ada")
    target.mkdir()
    return {"ok": True}

@app.post("/api/files/{root_key}/rename")
def rename_file_generic(root_key: str, req: RenameReq, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, req.path)
    if target == root:
        raise HTTPException(400, "Tidak bisa rename root")
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")
    new_name = _valid_name(req.new_name)
    dest = target.with_name(new_name)
    if dest.exists():
        raise HTTPException(409, "Nama tujuan sudah ada")
    target.rename(dest)
    return {"ok": True}

def _is_binary(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    bad = sum(1 for b in sample if b < 9 or (13 < b < 32) or b > 126)
    return bad / len(sample) > 0.30

@app.get("/api/files/{root_key}/content")
def get_file_content_generic(root_key: str, path: str, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, path)
    if not target.is_file():
        raise HTTPException(404, "File tidak ada")
    if target.stat().st_size > MAX_TEXT_SIZE:
        raise HTTPException(400, f"File > {MAX_TEXT_SIZE // 1024 // 1024} MB — terlalu besar untuk diedit")
    data = target.read_bytes()
    if _is_binary(data):
        raise HTTPException(400, "File binary — tidak bisa diedit sebagai teks")
    return {"content": data.decode("utf-8", errors="replace")}

@app.put("/api/files/{root_key}/content")
def put_file_content_generic(root_key: str, req: TextReq, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, req.path)
    if not target.is_file():
        raise HTTPException(404, "File tidak ada")
    data = req.content.encode("utf-8")
    if len(data) > MAX_TEXT_SIZE:
        raise HTTPException(400, f"File > {MAX_TEXT_SIZE // 1024 // 1024} MB — terlalu besar")
    target.write_bytes(data)
    return {"ok": True}

def _extract_member(dest: Path, member_path: str, archive_path: str) -> Path:
    p = (dest / member_path).resolve()
    if p != dest and dest not in p.parents:
        raise ValueError(f"Entry {archive_path} keluar dari folder tujuan (zip-slip)")
    return p

@app.post("/api/files/{root_key}/extract")
def extract_archive_generic(root_key: str, path: str, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, path)
    if not target.is_file():
        raise HTTPException(404, "File tidak ada")
    dest = target.parent
    name = target.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(target) as zf:
                for info in zf.infolist():
                    out = _extract_member(dest, info.filename, target.name)
                    if info.is_dir():
                        out.mkdir(parents=True, exist_ok=True)
                        continue
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as src, out.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
        elif name.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")):
            with tarfile.open(target) as tf:
                for m in tf.getmembers():
                    out = _extract_member(dest, m.name, target.name)
                    if m.isdir():
                        out.mkdir(parents=True, exist_ok=True)
                    elif m.isfile():
                        out.parent.mkdir(parents=True, exist_ok=True)
                        f = tf.extractfile(m)
                        if f is None:
                            continue
                        with f as src, out.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                    elif m.issym() or m.islnk():
                        continue
        else:
            raise HTTPException(400, "Format tidak didukung — pakai .zip/.tar/.tar.gz/.tgz")
    except zipfile.BadZipFile:
        raise HTTPException(400, "File zip rusak") from None
    except tarfile.TarError:
        raise HTTPException(400, "File tar rusak") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}

def _parse_mode(mode: str) -> int:
    if not re.fullmatch(r"[0-7]{3,4}", mode):
        raise HTTPException(400, "Mode harus oktal (contoh: 755, 0644)")
    return int(mode, 8)

@app.post("/api/files/{root_key}/chmod")
def chmod_file_generic(root_key: str, req: ChmodReq, user: dict = Depends(require_auth)) -> dict:
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, req.path)
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")
    mode = _parse_mode(req.mode)
    os.chmod(target, mode)
    return {"ok": True, "mode": oct(mode)}

@app.post("/api/files/{root_key}/chown")
def chown_file_generic(root_key: str, req: ChownReq, user: dict = Depends(require_auth)) -> dict:
    if not req.owner:
        raise HTTPException(400, "Owner kosong — format: user, user:group, atau :group")
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, req.path)
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")

    import grp
    import pwd

    user_part, _, group_part = req.owner.partition(":")
    uid = -1
    gid = -1
    if user_part:
        try:
            uid = int(user_part) if user_part.isdigit() else pwd.getpwnam(user_part).pw_uid
        except KeyError:
            raise HTTPException(400, f"User tidak ditemukan: {user_part}")
    if group_part:
        try:
            gid = int(group_part) if group_part.isdigit() else grp.getgrnam(group_part).gr_gid
        except KeyError:
            raise HTTPException(400, f"Group tidak ditemukan: {group_part}")
    os.chown(target, uid, gid)
    return {"ok": True, "owner": req.owner}

@app.get("/api/files/{root_key}/download")
def download_file_generic(root_key: str, path: str, user: dict = Depends(require_auth)):
    root = _get_allowed_root(root_key)
    target = _resolve_within(root, path)
    if not target.exists():
        raise HTTPException(404, "Path tidak ada")

    if target.is_file():
        return FileResponse(target, filename=target.name)

    buf = io.BytesIO()
    base = target.name or "folder"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(target.rglob("*")):
            if p.is_file():
                zf.write(p, str(p.relative_to(target.parent)))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{base}.zip"'},
    )