"""Monitoring: statistik dashboard + status SSL per-site.

Data dikumpulkan read-only: jumlah site/db/ftp/user, total ukuran folder
site, umur site, status SSL (folder letsencrypt live ada atau tidak) +
expiry dari cert.pem. Tidak ada agent/daemon — dihitung per request.

Alerting (email/webhook) bukan bagian fitur ini — YAGNI sampai ada
kebutuhan eksplisit.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
from pathlib import Path

from . import nginx

LETSENCRYPT_LIVE = Path(os.environ.get("CCPANEL_LETSENCRYPT_LIVE", "/etc/letsencrypt/live"))

def _folder_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

def _cert_expiry(domain: str) -> str | None:
    """Baca expiry cert.pem (format openssl). None kalau tak ada cert."""
    cert = LETSENCRYPT_LIVE / domain / "cert.pem"
    if not cert.is_file():
        return None
    res = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", str(cert)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    m = re.search(r"notAfter=(.+)", res.stdout)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").isoformat()
    except ValueError:
        return None

def dashboard(conn, owner_id: int | None = None) -> dict:
    """Hitung statistik panel. conn = koneksi DB aktif (pemanggil yang buka).
    owner_id=None → admin, lihat semua. owner_id set → client, hanya punyanya."""
    if owner_id is None:
        site_rows = conn.execute("SELECT * FROM sites").fetchall()
        db_count = conn.execute("SELECT COUNT(*) c FROM dbs").fetchone()["c"]
        ftp_count = conn.execute("SELECT COUNT(*) c FROM ftp_accounts").fetchone()["c"]
    else:
        site_rows = conn.execute(
            "SELECT * FROM sites WHERE owner_id = ?", (owner_id,)
        ).fetchall()
        db_count = conn.execute(
            "SELECT COUNT(*) c FROM dbs WHERE owner_id = ?", (owner_id,)
        ).fetchone()["c"]
        ftp_count = conn.execute(
            "SELECT COUNT(*) c FROM ftp_accounts f JOIN sites s ON s.id = f.site_id "
            "WHERE s.owner_id = ?", (owner_id,)
        ).fetchone()["c"]
    user_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    total_size = 0
    sites = []
    for s in site_rows:
        root = Path(s["root_path"])
        size = _folder_size(root)
        total_size += size
        sites.append({
            "id": s["id"],
            "domain": s["domain"],
            "enabled": bool(s["enabled"]),
            "waf_enabled": bool(s["waf_enabled"]),
            "size": size,
            "ssl_expiry": _cert_expiry(s["domain"]),
            "created_at": s["created_at"],
        })
    sites.sort(key=lambda x: x["domain"].lower())

    return {
        "counts": {
            "sites": len(site_rows),
            "dbs": db_count,
            "ftp": ftp_count,
            "users": user_count,
        },
        "total_size": total_size,
        "sites": sites,
    }
