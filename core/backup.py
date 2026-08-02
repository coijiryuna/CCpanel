"""Backup/restore site (folder tar.gz) + database (mysqldump).

Semua via subprocess argumen-list. Env override untuk test:
CCPANEL_BACKUP_DIR (default data/backups), CCPANEL_WWW_ROOT, CCPANEL_MYSQL_HOST/PASSWORD.
Nama file backup: <domain>.tar.gz dan <db_name>.sql.gz (untuk DB). Timestamp dipakai
untuk unik-kan kalau nama bentrok.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import nginx, validate

BACKUP_DIR = Path(os.environ.get("CCPANEL_BACKUP_DIR", Path(__file__).resolve().parent.parent / "data" / "backups"))
MYSQL_HOST = os.environ.get("CCPANEL_MYSQL_HOST", "localhost")
MYSQL_ROOT_PASSWORD = os.environ.get("CCPANEL_MYSQL_ROOT_PASSWORD", "")


class BackupError(Exception):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    return p.with_name(f"{p.stem}.{_stamp()}{p.suffix}")


def _mysqldump_cmd(db_name: str) -> list[str]:
    cmd = ["mysqldump", f"--host={MYSQL_HOST}", "--user=root"]
    if MYSQL_ROOT_PASSWORD:
        cmd.append(f"--password={MYSQL_ROOT_PASSWORD}")
    cmd += [db_name]
    return cmd


def _mysql_cmd() -> list[str]:
    cmd = ["mysql", f"--host={MYSQL_HOST}", "--user=root"]
    if MYSQL_ROOT_PASSWORD:
        cmd.append(f"--password={MYSQL_ROOT_PASSWORD}")
    return cmd


def backup_site(domain: str) -> Path:
    """Tar.gz folder root site. Raise kalau folder tidak ada."""
    root = nginx.root_path(domain)
    if not root.is_dir():
        raise BackupError(f"Folder root tidak ada: {root}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(BACKUP_DIR / f"{domain}.tar.gz")
    res = subprocess.run(
        ["tar", "-czf", str(dest), "-C", str(root.parent), root.name],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        dest.unlink(missing_ok=True)
        raise BackupError(res.stderr.strip() or "tar gagal")
    return dest


def backup_db(db_name: str) -> Path:
    """Dump DB ke .sql.gz via mysqldump. DB divalidasi dulu (whitelist nama)."""
    if not validate.valid_db_name(db_name):
        raise BackupError("nama DB tidak valid")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(BACKUP_DIR / f"{db_name}.sql.gz")
    with dest.open("wb") as f:
        dump = subprocess.run(_mysqldump_cmd(db_name), capture_output=True)
        if dump.returncode != 0:
            dest.unlink(missing_ok=True)
            raise BackupError(dump.stderr.decode(errors="replace").strip() or "mysqldump gagal")
        gz = subprocess.run(["gzip", "-c"], input=dump.stdout, capture_output=True)
        if gz.returncode != 0:
            dest.unlink(missing_ok=True)
            raise BackupError("gzip gagal")
        f.write(gz.stdout)
    return dest


def _backup_path(name: str) -> Path:
    """Resolve nama backup ke path di dalam BACKUP_DIR. Tolak traversal."""
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        raise BackupError("nama backup tidak valid")
    target = (BACKUP_DIR / name).resolve()
    if BACKUP_DIR.resolve() not in target.parents:
        raise BackupError("nama backup tidak valid")
    return target


def restore_site(backup_path: str) -> Path:
    """Extract tar.gz backup ke wwwroot. Nama folder diambil dari isi tar (root.name)."""
    src = _backup_path(backup_path)
    if not src.is_file():
        raise BackupError(f"Backup tidak ada: {src}")
    WWW = nginx.WWW_ROOT
    WWW.mkdir(parents=True, exist_ok=True)
    # cari folder pertama di dalam tar — itu root site
    listing = subprocess.run(
        ["tar", "-tzf", str(src)], capture_output=True, text=True,
    )
    if listing.returncode != 0:
        raise BackupError(listing.stderr.strip() or "tar list gagal")
    first = listing.stdout.strip().splitlines()
    if not first:
        raise BackupError("Backup kosong")
    domain_dir = first[0].split("/", 1)[0]
    root = (WWW / domain_dir).resolve()
    if not str(root).startswith(str(WWW.resolve())):
        raise BackupError("Backup berisi path di luar wwwroot")
    if root.exists():
        raise BackupError(f"Folder sudah ada: {root} — restore dulu site dari trash atau hapus folder")
    res = subprocess.run(
        ["tar", "-xzf", str(src), "-C", str(WWW)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise BackupError(res.stderr.strip() or "tar extract gagal")
    return root


def restore_db(backup_path: str, db_name: str) -> None:
    """Restore dump SQL ke database (harus sudah ada, mis. via create_db)."""
    if not validate.valid_db_name(db_name):
        raise BackupError("nama DB tidak valid")
    src = _backup_path(backup_path)
    if not src.is_file():
        raise BackupError(f"Backup tidak ada: {src}")
    # gunzip lalu pipe ke mysql
    gz = subprocess.run(["gzip", "-dc", str(src)], capture_output=True)
    if gz.returncode != 0:
        raise BackupError("gzip -dc gagal")
    res = subprocess.run(
        [*_mysql_cmd(), db_name], input=gz.stdout, capture_output=True,
    )
    if res.returncode != 0:
        raise BackupError(res.stderr.decode(errors="replace").strip() or "mysql restore gagal")


def list_backups() -> list[dict]:
    """Daftar backup: {name, type(site|db), size, mtime}. Kosong kalau dir tak ada."""
    if not BACKUP_DIR.is_dir():
        return []
    items = []
    for p in sorted(BACKUP_DIR.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file():
            continue
        if p.name.endswith(".tar.gz"):
            kind = "site"
        elif p.name.endswith(".sql.gz"):
            kind = "db"
        else:
            continue
        items.append({"name": p.name, "type": kind, "size": p.stat().st_size, "mtime": p.stat().st_mtime})
    return items
