"""Operasi Apache: vhost template, buat/hapus site, enable/disable.

Interface identik dengan core/nginx.py. Config dir via env
CCPANEL_APACHE_CONF_DIR (default /etc/apache2/sites-available).
WWW_ROOT/TRASH_DIR + trash items di-share dari core/nginx.
"""
from __future__ import annotations

import grp
import os
import pwd
import re
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

APACHE_CONF_DIR = Path(os.environ.get("CCPANEL_APACHE_CONF_DIR", "/etc/apache2/sites-available"))
SYSTEMCTL = os.environ.get("CCPANEL_SYSTEMCTL", "systemctl")
# Port backend multi-web-server (aaPanel): apache = 8288. Single mode = 80.
APACHE_PORT = int(os.environ.get("CCPANEL_APACHE_PORT", "8288"))

def _listen_port() -> int:
    """Port listen vhost: 80 single mode, backend port multi mode."""
    mode = os.environ.get("CCPANEL_WEBSERVER_MODE", "single").lower()
    return APACHE_PORT if mode == "multi" else 80

# ports.conf tempat Apache declare Listen (Debian/Ubuntu: /etc/apache2/ports.conf)
APACHE_PORTS_CONF = Path(os.environ.get("CCPANEL_APACHE_PORTS_CONF", "/etc/apache2/ports.conf"))

def _ensure_listen(port: int) -> None:
    """Multi mode: pastikan ports.conf punya `Listen <port>` utk backend.
    Tanpa ini `apachectl -t` error: Port <port> not defined."""
    if port == 80 or not APACHE_PORTS_CONF.exists():
        return
    text = APACHE_PORTS_CONF.read_text()
    if re.search(rf"^\s*Listen\s+{port}\s*$", text, re.M):
        return
    APACHE_PORTS_CONF.write_text(text.rstrip() + f"\nListen {port}\n")

VHOST_TEMPLATE = """<VirtualHost *:{port}>
    ServerAdmin webmaster@{domain}
    DocumentRoot "{root}"
    ServerName {domain}
    ServerAlias {domain}
    #errorDocument 404 /404.html
    IncludeOptional /www/server/panel/vhost/apache/extension/{domain}/*.conf
    ErrorLog "/www/wwwlogs/{domain}-error_log"
    CustomLog "/www/wwwlogs/{domain}-access_log" combined

    # Security Headers
    Header always set X-Frame-Options "SAMEORIGIN"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-XSS-Protection "1; mode=block"
    Header always set Referrer-Policy "no-referrer-when-downgrade"
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"

    #DENY FILES
     <Files ~ (\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md)$>
       Order allow,deny
       Deny from all
    </Files>
    
    #PHP
    <FilesMatch \\.php$>
            SetHandler "proxy:unix:/tmp/php-cgi-00.sock|fcgi://localhost"
    </FilesMatch>
    
    #PATH
    <Directory "{root}">
        SetOutputFilter DEFLATE
        Options FollowSymLinks
        AllowOverride All
        Require all granted
        DirectoryIndex index.php index.html index.htm default.php default.html default.htm
    </Directory>

    #Obtain the reverse proxy ip start   
    RemoteIPTrustedProxy 127.0.0.1
    RemoteIPHeader X-Real-IP
    #Obtain the reverse proxy ip end
</VirtualHost>
"""

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def vhost_path(domain: str) -> Path:
    return APACHE_CONF_DIR / f"{domain}.conf"


def root_path(domain: str) -> Path:
    return WWW_ROOT / domain

def _get_web_user_uid_gid() -> tuple[int, int]:
    """Get uid/gid for web user (www atau www-data). Apache requires UID >= 11, GID >= 10."""
    for user in ("www-data", "www"):
        try:
            pw = pwd.getpwnam(user)
            gr = grp.getgrgid(pw.pw_gid)
            if pw.pw_uid >= 11 and gr.gr_gid >= 10:
                return pw.pw_uid, gr.gr_gid
        except KeyError:
            continue
    # Fallback: use first available user with uid >= 11
    try:
        for i in range(11, 100):
            try:
                pw = pwd.getpwuid(i)
                gr = grp.getgrgid(pw.pw_gid)
                if gr.gr_gid >= 10:
                    return i, gr.gr_gid
            except KeyError:
                continue
    except Exception:
        pass
    # Last resort: use www-data or www if available
    for user in ("www-data", "www"):
        try:
            pw = pwd.getpwnam(user)
            return pw.pw_uid, pw.pw_gid
        except KeyError:
            continue
    raise WebserverError("Cannot find suitable web user for directory ownership (uid >= 11, gid >= 10)")

def test() -> None:
    res = _run(["apachectl", "-t"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or res.stdout.strip() or "apachectl -t failed")


def reload() -> None:
    # skip reload kalau service tak aktif (mis. apache diinstall tapi belum start)
    if _run([SYSTEMCTL, "is-active", "--quiet", "apache2"]).returncode != 0:
        return
    res = _run([SYSTEMCTL, "reload", "apache2"])
    if res.returncode != 0:
        raise WebserverError(res.stderr.strip() or "systemctl reload apache2 failed")


def _write_vhost(domain: str, root: Path, running_dir: str = "") -> None:
    APACHE_CONF_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_listen(_listen_port())
    doc_root = str(root / running_dir) if running_dir else str(root)
    conf = VHOST_TEMPLATE.format(domain=domain, root=doc_root, port=_listen_port())
    vhost_path(domain).write_text(conf)

def _write_vhost_with_features(domain: str, root: Path, features: dict) -> None:
    """Write vhost with custom feature flags (for config modal updates) - aaPanel style."""
    APACHE_CONF_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_listen(_listen_port())
    
    # Build vhost with feature flags
    deny_files = features.get("deny_files", True)
    remote_ip = features.get("remote_ip", True)
    deflate = features.get("deflate", True)
    directory_index = features.get("directory_index", "index.php index.html index.htm default.php default.html default.htm")
    server_admin = features.get("server_admin", f"webmaster@{domain}")
    error_log_path = features.get("error_log_path", "/www/wwwlogs/")
    custom_log_path = features.get("custom_log_path", "/www/wwwlogs/")
    running_dir = features.get("running_dir", "")
    
    deny_block = ""
    if deny_files:
        deny_block = """    #DENY FILES
     <Files ~ (\\.user.ini|\\.htaccess|\\.git|\\.env|\\.svn|\\.project|LICENSE|README.md)$>
       Order allow,deny
       Deny from all
    </Files>
"""
    
    remote_ip_block = ""
    if remote_ip:
        remote_ip_block = """    #Obtain the reverse proxy ip start   
    RemoteIPTrustedProxy 127.0.0.1
    RemoteIPHeader X-Real-IP
    #Obtain the reverse proxy ip end
"""
    
    deflate_line = "        SetOutputFilter DEFLATE\n" if deflate else ""
    
    doc_root = str(root / running_dir) if running_dir else str(root)
    
    conf = f"""<VirtualHost *:{_listen_port()}>
    ServerAdmin {server_admin}
    DocumentRoot "{doc_root}"
    ServerName {domain}
    ServerAlias {domain}
    #errorDocument 404 /404.html
    IncludeOptional /www/server/panel/vhost/apache/extension/{domain}/*.conf
    ErrorLog "{error_log_path}{domain}-error_log"
    CustomLog "{custom_log_path}{domain}-access_log" combined

{deny_block}    #PHP
    <FilesMatch \\.php$>
            SetHandler "proxy:unix:/tmp/php-cgi-00.sock|fcgi://localhost"
    </FilesMatch>
    
    #PATH
    <Directory "{doc_root}">
{deflate_line}        Options FollowSymLinks
        AllowOverride All
        Require all granted
        DirectoryIndex {directory_index}
    </Directory>

{remote_ip_block}</VirtualHost>
"""
    vhost_path(domain).write_text(conf)


def create_site(domain: str, running_dir: str = "") -> Path:
    root = root_path(domain)
    if root.exists():
        raise WebserverError(f"Folder root sudah ada: {root}")
    try:
        root.mkdir(parents=True, exist_ok=False)
        # Set proper ownership: Apache requires uid >= 11 and gid >= 10
        try:
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
        except (PermissionError, OSError):
            # In test/dev environment may not have chown permission — continue anyway
            # In production, this should succeed if running as root
            pass
    except FileExistsError:
        raise WebserverError(f"Folder root sudah ada: {root}") from None
    try:
        (root / "index.html").write_text(DEFAULT_INDEX.format(domain=domain))
        _write_vhost(domain, root, running_dir)
        nginx_test()
    except Exception as e:
        vhost_path(domain).unlink(missing_ok=True)
        shutil.rmtree(root, ignore_errors=True)
        if isinstance(e, WebserverError):
            raise
        raise WebserverError(f"create_site failed: {e}") from e
    nginx_reload()
    return root


def activate_site(domain: str, running_dir: str = "") -> None:
    root = root_path(domain)
    if not root.is_dir():
        raise WebserverError(f"Folder root tidak ada: {root}")
    if vhost_path(domain).exists():
        raise WebserverError(f"vhost {vhost_path(domain)} sudah ada")
    _write_vhost(domain, root, running_dir)
    try:
        nginx_test()
    except WebserverError:
        vhost_path(domain).unlink(missing_ok=True)
        raise
    nginx_reload()


def fix_vhost_ownership(domain: str) -> None:
    """Fix directory ownership for existing vhost (uid >= 11, gid >= 10).
    
    Use this to fix Apache warnings on existing vhosts that were created
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
