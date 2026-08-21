"""SSL via certbot (plugin nginx). certbot mengedit vhost otomatis.

Prasyarat: paket python3-certbot-nginx terpasang, domain punya DNS A record.
Kalau email kosong/invalid, certbot pakai mode tanpa email.
Rollback: backup vhost sebelum jalan, restore kalau gagal.
"""
from __future__ import annotations

import os
import re
import subprocess
import sqlite3
from pathlib import Path

from . import nginx


class CertError(Exception):
    pass


def _get_certbot_email() -> str:
    # Try to read from the database first
    try:
        BASE_DIR = Path(__file__).resolve().parent.parent
        data_dir = Path(os.environ.get("CCPANEL_DATA_DIR", BASE_DIR / "data"))
        db_path = data_dir / "ccpanel.db"
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'certbot_email'"
            ).fetchone()
            if row:
                return row["value"].strip()
    except Exception:
        pass
    # If database doesn't have it, try environment variable
    email = os.environ.get("CCPANEL_CERTBOT_EMAIL")
    if email:
        return email.strip()
    return ""


def _email_arg() -> list[str]:
    email = _get_certbot_email()
    if not email:
        return ["--register-unsafely-without-email"]
    # ponytail: validasi ringan; upgrade path: email-validator kalau perlu.
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return ["--register-unsafely-without-email"]
    return ["-m", email]


def install_ssl(domain: str, extra_domains: list[str] | None = None) -> None:
    vh = nginx.vhost_path(domain)
    if not vh.exists():
        raise CertError(f"vhost {vh} tidak ada")

    backup = vh.read_text()
    names = [domain] + [d for d in (extra_domains or []) if d and d != domain]
    cmd = [
        "certbot", "--nginx",
    ] + [item for d in names for item in ("-d", d)] + [
        "--non-interactive", "--agree-tos",
    ] + _email_arg()
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        vh.write_text(backup)
        nginx.nginx_reload()
        raise CertError(res.stderr.strip()
                        or res.stdout.strip() or "certbot failed")
    # Log full output for debugging
    import logging
    logging.info(f"certbot install output: {res.stdout}")

    try:
        nginx.nginx_test()
    except nginx.NginxError:
        vh.write_text(backup)
        nginx.nginx_reload()
        raise
    nginx.nginx_reload()


def renew_all() -> None:
    """Renew semua cert yang mendekati expiry. Return True kalau ada yang di-renew."""
    cmd = ["certbot", "renew", "--nginx", "--non-interactive"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise CertError(res.stderr.strip() or res.stdout.strip()
                        or "certbot renew failed")
    nginx.nginx_reload()
