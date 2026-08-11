"""Operasi OpenLiteSpeed: vhost template, buat/hapus site, enable/disable.

OpenLiteSpeed baca config per-site dari /usr/local/lsws/conf/vhosts/
(include via httpd_config.conf). Config dir via env
CCPANEL_LSWS_CONF_DIR. WWW_ROOT/TRASH_DIR di-share dari core/nginx.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import validate
from .nginx import (
    DEFAULT_INDEX,
    NginxError as WebserverError,
    TRASH_DIR,
    WWW_ROOT,
    purge_site,
    trash_items,
)

LSWS_CONF_DIR = Path(os.environ.get("CCPANEL_LSWS_CONF_DIR", "/usr/local/lsws/conf/vhosts"))
LSWS_BIN = os.environ.get("CCPANEL_LSWS_BIN", "/usr/local/lsws/bin/lshttpd")

VHOST_TEMPLATE = """docroot                   {root}/
vhDomain                  {domain}
enableGzip                1
errorlog                  $VH_ROOT/logs/error.log
accesslog                 $VH_ROOT/logs/access.log $VH_NAME
index                     index.html index.htm

rewrite  {{
    enable                 1
    autoLoadHtaccess       1
}}

realm {domain} {{
    type  protected
}}
"""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def vhost_path(domain: str) -> Path:
    return LSWS_CONF_DIR / f"{domain}.conf"


def root_path(domain: str) -> Path:
    return WWW_ROOT / domain


def nginx_test() -> None:
    res = _run([LSWS_BIN, "-t"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or res.stdout.strip() or "lshttpd -t failed")


def nginx_reload() -> None:
    res = _run([LSWS_BIN, "restart"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or "lshttpd restart failed")


def _write_vhost(domain: str, root: Path) -> None:
    LSWS_CONF_DIR.mkdir(parents=True, exist_ok=True)
    conf = VHOST_TEMPLATE.format(domain=domain, root=root)
    vhost_path(domain).write_text(conf)


def create_site(domain: str) -> Path:
    root = root_path(domain)
    if root.exists():
        raise WebserverError(f"Folder root sudah ada: {root}")
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise WebserverError(f"Folder root sudah ada: {root}") from None
    try:
        (root / "index.html").write_text(DEFAULT_INDEX.format(domain=domain))
        _write_vhost(domain, root)
        nginx_test()
    except Exception as e:
        vhost_path(domain).unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)
        if isinstance(e, WebserverError):
            raise
        raise WebserverError(f"create_site failed: {e}") from e
    nginx_reload()
    return root


def activate_site(domain: str) -> None:
    root = root_path(domain)
    if not root.is_dir():
        raise WebserverError(f"Folder root tidak ada: {root}")
    if vhost_path(domain).exists():
        raise WebserverError(f"vhost {vhost_path(domain)} sudah ada")
    _write_vhost(domain, root)
    try:
        nginx_test()
    except WebserverError:
        vhost_path(domain).unlink(missing_ok=True)
        raise
    nginx_reload()


def set_enabled(domain: str, enabled: bool) -> None:
    vh = vhost_path(domain)
    disabled = vh.with_name(vh.name + ".disabled")
    if enabled:
        if not disabled.exists():
            raise WebserverError(f"vhost {vh} tidak ada")
        disabled.rename(vh)
    else:
        if not vh.exists():
            raise WebserverError(f"vhost {vh} tidak ada")
        vh.rename(disabled)
    try:
        nginx_test()
    except WebserverError:
        if enabled:
            vh.rename(disabled)
        else:
            disabled.rename(vh)
        raise
    nginx_reload()


def remove_vhost(domain: str) -> None:
    """Hapus vhost saja — root TETAP. Untuk switch engine antar server."""
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        nginx_test()
    except WebserverError:
        if backup is not None:
            vh.write_text(backup)
        raise
    nginx_reload()

def remove_site(domain: str) -> None:
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        nginx_test()
    except WebserverError:
        if backup is not None:
            vh.write_text(backup)
        raise
    nginx_reload()

    root = root_path(domain)
    if root.exists():
        TRASH_DIR.mkdir(parents=True, exist_ok=True)
        dest = TRASH_DIR / domain
        if dest.exists():
            import time

            dest = TRASH_DIR / f"{domain}.{int(time.time())}"
        shutil.move(str(root), str(dest))


def restore_site(trash_name: str) -> str:
    import re

    src = TRASH_DIR / trash_name
    if not src.is_dir():
        raise WebserverError(f"Trash item tidak ada: {trash_name}")
    m = re.match(r"^(.*)\.(\d{10})$", trash_name)
    domain = m.group(1) if m else trash_name
    if not validate.valid_domain(domain):
        raise WebserverError(f"Nama trash tidak valid: {trash_name}")

    root = root_path(domain)
    if root.exists():
        raise WebserverError(f"Folder root sudah ada: {root} — restore dibatalkan")
    vh = vhost_path(domain)
    if vh.exists():
        raise WebserverError(f"vhost {vh} sudah ada — restore dibatalkan")

    try:
        shutil.move(str(src), str(root))
        _write_vhost(domain, root)
        nginx_test()
    except Exception as e:
        vh.unlink(missing_ok=True)
        if root.exists() and not src.exists():
            shutil.move(str(root), str(src))
        if isinstance(e, WebserverError):
            raise
        raise WebserverError(f"restore_site failed: {e}") from e
    nginx_reload()
    return domain
