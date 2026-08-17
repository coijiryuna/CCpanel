"""Operasi OpenLiteSpeed: vhost template, buat/hapus site, enable/disable.

OpenLiteSpeed baca config per-site dari /usr/local/lsws/conf/vhosts/
(include via httpd_config.conf). Config dir via env
CCPANEL_LSWS_CONF_DIR. WWW_ROOT/TRASH_DIR di-share dari core/nginx.
"""
from __future__ import annotations

import grp
import os
import pwd
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
# Port backend multi-web-server (aaPanel): OpenLiteSpeed = 8188. Single = 80.
# Catatan: listener OLS dikonfig di httpd_config.conf (level server), bukan
# per-vhost. Nilai ini utk dokumentasi + validasi nginx front proxy.
LSWS_PORT = int(os.environ.get("CCPANEL_LSWS_PORT", "8188"))

def _listen_port() -> int:
    """Port listen vhost: 80 single mode, backend port multi mode."""
    mode = os.environ.get("CCPANEL_WEBSERVER_MODE", "single").lower()
    return LSWS_PORT if mode == "multi" else 80

VHOST_TEMPLATE = """docroot                   {root}/
vhDomain                  {domain}
enableGzip                1
enableIpGeo               1

# Security Headers
header_out X-Frame-Options "SAMEORIGIN"
header_out X-Content-Type-Options "nosniff"
header_out X-XSS-Protection "1; mode=block"
header_out Referrer-Policy "no-referrer-when-downgrade"
header_out Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"

index  {{
    useServer               0
    indexFiles              index.php,index.html,index.htm
}}

errorlog $VH_ROOT/logs/error.log {{
    useServer               0
    logLevel                ERROR
    rollingSize             10M
}}

accesslog $VH_ROOT/logs/access.log {{
    useServer               0
    logFormat               '%{{X-Forwarded-For}}i %h %l %u %t "%r" %>s %b "%{{Referer}}i" "%{{User-Agent}}i"'
    logHeaders              5
    rollingSize             10M
    keepDays                10
    compressArchive         1
}}

scripthandler  {{
    add                     lsapi:{domain} php
}}

extprocessor {domain} {{
    type                    lsapi
    address                 UDS://tmp/lshttpd/{domain}.sock
    maxConns                300
    env                     LSAPI_CHILDREN=300
    env                     LSAPI_AVOID_FORK=1
    initTimeout             600
    retryTimeout            5
    persistConn             1
    pcKeepAliveTimeout      30
    respBuffer              0
    autoStart               1
    path                    /usr/local/lsws/lsphp00/bin/lsphp
    extUser                 nobody
    extGroup                nogroup
    memSoftLimit            2047M
    memHardLimit            2047M
    procSoftLimit           1000
    procHardLimit           1100
}}

expires {{
    enableExpires           1
    expiresByType           image/*=A43200,text/css=A43200,application/x-javascript=A43200,application/javascript=A43200,font/*=A43200,application/x-font-ttf=A43200
}}

rewrite  {{
    enable                  1
    autoLoadHtaccess        1
}}
"""


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def vhost_path(domain: str) -> Path:
    return LSWS_CONF_DIR / f"{domain}.conf"


def root_path(domain: str) -> Path:
    return WWW_ROOT / domain


def _get_web_user_uid_gid() -> tuple[int, int]:
    """Get uid/gid for web user. LiteSpeed requires uid >= 11, gid >= 10."""
    for user_name in ("www-data", "nobody", "www"):
        try:
            pw = pwd.getpwnam(user_name)
            gr = grp.getgrgid(pw.pw_gid)
            if pw.pw_uid >= 11 and gr.gr_gid >= 10:
                return pw.pw_uid, gr.gr_gid
        except KeyError:
            continue
    for pw in pwd.getpwall():
        try:
            gr = grp.getgrgid(pw.pw_gid)
            if pw.pw_uid >= 11 and gr.gr_gid >= 10:
                return pw.pw_uid, gr.gr_gid
        except KeyError:
            continue
    raise WebserverError(
        "Cannot find suitable web user for directory ownership (uid >= 11, gid >= 10 required)")


def test() -> None:
    res = _run([LSWS_BIN, "-t"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or res.stdout.strip() or "lshttpd -t failed")


def reload() -> None:
    res = _run([LSWS_BIN, "restart"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or "lshttpd restart failed")


def _write_vhost(domain: str, root: Path, running_dir: str = "") -> None:
    LSWS_CONF_DIR.mkdir(parents=True, exist_ok=True)
    doc_root = str(root / running_dir) if running_dir else str(root)
    conf = VHOST_TEMPLATE.format(domain=domain, root=doc_root)
    vhost_path(domain).write_text(conf)

def _write_vhost_with_features(domain: str, root: Path, features: dict) -> None:
    """Write vhost with custom feature flags (for config modal updates) - OLS format."""
    LSWS_CONF_DIR.mkdir(parents=True, exist_ok=True)
    
    # Build vhost with feature flags
    deny_files = features.get("deny_files", True)
    remote_ip = features.get("remote_ip", True)
    deflate = features.get("deflate", True)
    directory_index = features.get("directory_index", "index.php index.html index.htm default.php default.html default.htm")
    server_admin = features.get("server_admin", f"webmaster@{domain}")
    error_log_path = features.get("error_log_path", "/www/wwwlogs/")
    custom_log_path = features.get("custom_log_path", "/www/wwwlogs/")
    running_dir = features.get("running_dir", "")
    
    doc_root = str(root / running_dir) if running_dir else str(root)
    
    # OLS uses different format - add context blocks for deny files and remote IP
    deny_context = ""
    if deny_files:
        deny_context = f"""
context / {{
    location                {doc_root}/
    allowBrowse             1
    rewrite  {{
        enable                  1
        autoLoadHtaccess        1
    }}
    #DENY FILES
    <Files ~ (\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md)$>
        Order allow,deny
        Deny from all
    </Files>
}}"""
    
    # OLS doesn't use RemoteIP module like Apache - it gets real IP from X-Forwarded-For header
    # The nginx front proxy already sets X-Real-IP and X-Forwarded-For
    
    conf = f"""docroot                   {doc_root}/
vhDomain                  {domain}
enableGzip                1
enableIpGeo               1

index  {{
    useServer               0
    indexFiles              {directory_index.replace(' ', ',')}
}}

errorlog $VH_ROOT/logs/error.log {{
    useServer               0
    logLevel                ERROR
    rollingSize             10M
}}

accesslog $VH_ROOT/logs/access.log {{
    useServer               0
    logFormat               '%{{X-Forwarded-For}}i %h %l %u %t "%r" %>s %b "%{{Referer}}i" "%{{User-Agent}}i"'
    logHeaders              5
    rollingSize             10M
    keepDays                10
    compressArchive         1
}}

scripthandler  {{
    add                     lsapi:{domain} php
}}

extprocessor {domain} {{
    type                    lsapi
    address                 UDS://tmp/lshttpd/{domain}.sock
    maxConns                300
    env                     LSAPI_CHILDREN=300
    env                     LSAPI_AVOID_FORK=1
    initTimeout             600
    retryTimeout            5
    persistConn             1
    pcKeepAliveTimeout      30
    respBuffer              0
    autoStart               1
    path                    /usr/local/lsws/lsphp00/bin/lsphp
    extUser                 nobody
    extGroup                nogroup
    memSoftLimit            2047M
    memHardLimit            2047M
    procSoftLimit           1000
    procHardLimit           1100
}}

expires {{
    enableExpires           1
    expiresByType           image/*=A43200,text/css=A43200,application/x-javascript=A43200,application/javascript=A43200,font/*=A43200,application/x-font-ttf=A43200
}}

rewrite  {{
    enable                  1
    autoLoadHtaccess        1
}}{deny_context}
"""
    vhost_path(domain).write_text(conf)


def create_site(domain: str, running_dir: str = "") -> Path:
    root = root_path(domain)
    if root.exists():
        raise WebserverError(f"Folder root sudah ada: {root}")
    try:
        root.mkdir(parents=True, exist_ok=False)
        # Set proper ownership: LiteSpeed requires uid >= 11 and gid >= 10
        uid, gid = _get_web_user_uid_gid()
        os.chown(root, uid, gid)
        # Also fix parent directories if needed (recursively up to WWW_ROOT)
        parent = root.parent
        while parent != WWW_ROOT.parent and parent.exists():
            try:
                os.chown(parent, uid, gid)
            except (PermissionError, OSError):
                pass
            parent = parent.parent
    except FileExistsError:
        raise WebserverError(f"Folder root sudah ada: {root}") from None
    try:
        (root / "index.html").write_text(DEFAULT_INDEX.format(domain=domain))
        _write_vhost(domain, root, running_dir)
        test()
    except Exception as e:
        vhost_path(domain).unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)
        if isinstance(e, WebserverError):
            raise
        raise WebserverError(f"create_site failed: {e}") from e
    reload()
    return root


def activate_site(domain: str, running_dir: str = "") -> None:
    root = root_path(domain)
    if not root.is_dir():
        raise WebserverError(f"Folder root tidak ada: {root}")
    if vhost_path(domain).exists():
        raise WebserverError(f"vhost {vhost_path(domain)} sudah ada")
    _write_vhost(domain, root, running_dir)
    try:
        test()
    except WebserverError:
        vhost_path(domain).unlink(missing_ok=True)
        raise
    reload()


def fix_vhost_ownership(domain: str) -> None:
    """Fix directory ownership for existing vhost (uid >= 11, gid >= 10).
    
    Use this to fix LiteSpeed warnings on existing vhosts that were created
    with root ownership. Requires running as root or with sufficient privileges.
    """
    root = root_path(domain)
    if not root.is_dir():
        raise WebserverError(f"Folder root tidak ada: {root}")
    try:
        uid, gid = _get_web_user_uid_gid()
        os.chown(root, uid, gid)
        # Also fix nested directories recursively
        for dirpath, dirnames, filenames in os.walk(root):
            for dirname in dirnames:
                full_path = os.path.join(dirpath, dirname)
                try:
                    os.chown(full_path, uid, gid)
                except (PermissionError, OSError):
                    pass
    except (PermissionError, OSError) as e:
        raise WebserverError(f"fix_vhost_ownership failed (requires root): {e}") from e


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
        test()
    except WebserverError:
        if enabled:
            vh.rename(disabled)
        else:
            disabled.rename(vh)
        raise
    reload()


def remove_vhost(domain: str) -> None:
    """Hapus vhost saja — root TETAP. Untuk switch engine antar server."""
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        test()
    except WebserverError:
        if backup is not None:
            vh.write_text(backup)
        raise
    reload()

def remove_site(domain: str) -> None:
    vh = vhost_path(domain)
    backup = vh.read_text() if vh.exists() else None
    if backup is not None:
        vh.unlink()
    try:
        test()
    except WebserverError:
        if backup is not None:
            vh.write_text(backup)
        raise
    reload()

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
        test()
    except Exception as e:
        vh.unlink(missing_ok=True)
        if root.exists() and not src.exists():
            shutil.move(str(root), str(src))
        if isinstance(e, WebserverError):
            raise
        raise WebserverError(f"restore_site failed: {e}") from e
    reload()
    return domain
