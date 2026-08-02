"""Dispatcher web server engine: nginx (default) / apache / litespeed.

server.py hanya bicara ke modul ini — pilih engine aktif dari env
CCPANEL_WEBSERVER (default nginx). Interface umum:
  create_site / activate_site / set_enabled / remove_site
  trash_items / restore_site / purge_site
  vhost_path / root_path / test / reload
NginxError lama → WebserverError (alias biar import lama tetap jalan).
"""
from __future__ import annotations

import os

from . import apache, litespeed, nginx

ENGINES = {
    "nginx": nginx,
    "apache": apache,
    "litespeed": litespeed,
}

ACTIVE = os.environ.get("CCPANEL_WEBSERVER", "nginx").lower()
if ACTIVE not in ENGINES:
    ACTIVE = "nginx"

# alias error biar pengecualian lama (except nginx.NginxError) tetap jalan
WebserverError = nginx.NginxError


def set_active(engine: str) -> None:
    """Ganti engine aktif (runtime). Fallback nginx kalau tidak dikenal."""
    global ACTIVE
    engine = engine.lower()
    ACTIVE = engine if engine in ENGINES else "nginx"


def for_engine(engine: str):
    """Ambil modul engine spesifik (untuk operasi per-site). Fallback nginx."""
    return ENGINES.get(engine.lower(), ENGINES["nginx"])


def _engine():
    return ENGINES[ACTIVE]


def create_site(domain: str):
    return _engine().create_site(domain)


def activate_site(domain: str) -> None:
    return _engine().activate_site(domain)


def set_enabled(domain: str, enabled: bool) -> None:
    return _engine().set_enabled(domain, enabled)


def remove_site(domain: str) -> None:
    return _engine().remove_site(domain)


def trash_items() -> list[dict]:
    return _engine().trash_items()


def restore_site(trash_name: str) -> str:
    return _engine().restore_site(trash_name)


def purge_site(trash_name: str) -> None:
    return _engine().purge_site(trash_name)


def vhost_path(domain: str):
    return _engine().vhost_path(domain)


def root_path(domain: str):
    return _engine().root_path(domain)


def nginx_proxy_insert(domain: str, subpath: str, port: int) -> None:
    """Proxy subpath -> 127.0.0.1:port. Khusus nginx (syntax location)."""
    return nginx.proxy_insert(domain, subpath, port)


def nginx_proxy_remove(domain: str, subpath: str) -> None:
    return nginx.proxy_remove(domain, subpath)


def nginx_proxy_enable(domain: str, port: int) -> None:
    """Proxy penuh: vhost listen port + location / -> app. Khusus nginx."""
    return nginx.proxy_enable(domain, port)


def nginx_proxy_disable(domain: str) -> None:
    return nginx.proxy_disable(domain)


def nginx_set_server_names(domain: str, names: list[str]) -> None:
    return nginx.set_server_names(domain, names)


def read_vhost(domain: str) -> str:
    """Isi file konfigurasi vhost."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise WebserverError(f"vhost {vh} tidak ada")
    return vh.read_text()


def write_vhost(domain: str, content: str) -> None:
    """Tulis konfigurasi vhost + test + reload. Rollback kalau test gagal."""
    vh = vhost_path(domain)
    if not vh.exists():
        raise WebserverError(f"vhost {vh} tidak ada")
    backup = vh.read_text()
    vh.write_text(content)
    try:
        test()
    except WebserverError:
        vh.write_text(backup)
        raise
    reload()


def test() -> None:
    return _engine().nginx_test()


def reload() -> None:
    return _engine().nginx_reload()
