"""SSL via certbot (plugin nginx). certbot mengedit vhost otomatis.

Prasyarat: paket python3-certbot-nginx terpasang, domain punya DNS A record,
env CCPANEL_CERTBOT_EMAIL diset.
Rollback: backup vhost sebelum jalan, restore kalau gagal.
"""
from __future__ import annotations

import os
import subprocess

from . import nginx

CERTBOT_EMAIL = os.environ.get("CCPANEL_CERTBOT_EMAIL", "")


class CertError(Exception):
    pass


def install_ssl(domain: str, extra_domains: list[str] | None = None) -> None:
    if not CERTBOT_EMAIL:
        raise CertError("CCPANEL_CERTBOT_EMAIL belum diset")
    vh = nginx.vhost_path(domain)
    if not vh.exists():
        raise CertError(f"vhost {vh} tidak ada")

    backup = vh.read_text()
    names = [domain] + [d for d in (extra_domains or []) if d and d != domain]
    cmd = [
        "certbot", "--nginx",
    ] + [item for d in names for item in ("-d", d)] + [
        "--non-interactive", "--agree-tos", "-m", CERTBOT_EMAIL,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        vh.write_text(backup)
        nginx.nginx_reload()
        raise CertError(res.stderr.strip() or res.stdout.strip() or "certbot failed")

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
        raise CertError(res.stderr.strip() or res.stdout.strip() or "certbot renew failed")
    nginx.nginx_reload()
