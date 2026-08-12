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

# --- Mode multi-web-server (arsitektur aaPanel) ---
# single: engine aktif pegang 80/443 sendiri.
# multi : nginx front di 80/443, apache backend 8288, OpenLiteSpeed 8188.
#         Site engine non-nginx dapat nginx vhost proxy -> port backend.
MODES = ("single", "multi")
BACKEND_PORTS = {
    "apache": int(os.environ.get("CCPANEL_APACHE_PORT", "8288")),
    "litespeed": int(os.environ.get("CCPANEL_LSWS_PORT", "8188")),
}

# alias error biar pengecualian lama (except nginx.NginxError) tetap jalan
WebserverError = nginx.NginxError

def mode() -> str:
    """Mode aktif: single / multi (env override utk testing)."""
    m = os.environ.get("CCPANEL_WEBSERVER_MODE", "single").lower()
    return m if m in MODES else "single"

def set_mode(m: str) -> None:
    """Ganti mode runtime. Simpan ke env biar modul lain baca konsisten."""
    m = (m or "").strip().lower()
    if m not in MODES:
        raise ValueError(f"Mode tidak valid: {m}. Pilihan: {', '.join(MODES)}")
    os.environ["CCPANEL_WEBSERVER_MODE"] = m

def is_multi() -> bool:
    """True = multi-web-server: nginx front + backend engine port khusus."""
    return mode() == "multi"

def backend_port(engine: str) -> int:
    """Port backend engine (multi mode). Single mode = 80 (tidak dipakai proxy)."""
    return BACKEND_PORTS.get(engine.lower(), 80)


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


def front_proxy_enable(domain: str, port: int) -> None:
    """Multi mode: nginx vhost front (80) proxy -> 127.0.0.1:port backend.
    Dipanggil utk site yang dilayani engine backend (apache/litespeed)."""
    return nginx.front_proxy_enable(domain, port)


def front_proxy_disable(domain: str) -> None:
    """Multi mode: balik nginx vhost front ke static (site dilayani nginx)."""
    return nginx.front_proxy_disable(domain)


def create_site(domain: str, running_dir: str = ""):
    return _engine().create_site(domain, running_dir)


def activate_site(domain: str, running_dir: str = "") -> None:
    return _engine().activate_site(domain, running_dir)


def set_enabled(domain: str, enabled: bool) -> None:
    return _engine().set_enabled(domain, enabled)


def remove_site(domain: str) -> None:
    return _engine().remove_site(domain)

def remove_vhost(domain: str) -> None:
    """Hapus vhost saja (root tetap) — untuk switch engine per-site.
    Engine tak punya remove_vhost = fallback remove_site (lama)."""
    fn = getattr(_engine(), "remove_vhost", None)
    if fn is None:
        return remove_site(domain)
    return fn(domain)


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
