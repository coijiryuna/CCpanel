"""Operasi PHP-FPM: pool config per-site, enable/disable PHP version.

Config dir via env CCPANEL_PHP_FPM_DIR (default /etc/php/*/fpm/pool.d).
WWW_ROOT/TRASH_DIR di-share dari core/nginx.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import webserver as webserver_ops
from .nginx import WWW_ROOT

PHP_VERSIONS = ["php8.1", "php8.2", "php8.3"]
DEFAULT_PHP_VERSION = "static"

PHP_FPM_DIR = Path(os.environ.get("CCPANEL_PHP_FPM_DIR", "/etc/php"))

PHP_VHOST_BEGIN = "# BEGIN CCPANEL PHP"
PHP_VHOST_END = "# END CCPANEL PHP"

def _php_location_block(domain: str, php_version: str) -> str:
    ver = php_version[3:]  # "8.1"
    return f"""    {PHP_VHOST_BEGIN}
    location ~ \\.php$ {{
        include fastcgi_params;
        fastcgi_pass unix:/run/php/php{ver}-fpm-{domain}.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }}
    {PHP_VHOST_END}
"""

class PhpError(Exception):
    pass

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)

def _php_fpm_pool_dir(php_version: str) -> Path:
    """Return pool.d directory for given PHP version."""
    return PHP_FPM_DIR / php_version / "fpm" / "pool.d"

def pool_path(domain: str, php_version: str) -> Path:
    """Return pool config file path for domain and PHP version."""
    return _php_fpm_pool_dir(php_version) / f"{domain}.conf"

def root_path(domain: str) -> Path:
    return WWW_ROOT / domain

def php_fpm_test(php_version: str) -> None:
    """Test PHP-FPM configuration for given version."""
    res = _run(["php-fpm" + php_version[3:], "-t"])
    if res.returncode != 0:
        raise PhpError(res.stderr.strip() or res.stdout.strip() or f"php-fpm{php_version[3:]} -t failed")

def php_fpm_reload(php_version: str) -> None:
    """Reload PHP-FPM for given version."""
    res = _run(["systemctl", "reload", f"php{php_version[3:]}-fpm"])
    if res.returncode != 0:
        raise PhpError(res.stderr.strip() or f"systemctl reload php{php_version[3:]}-fpm failed")

POOL_TEMPLATE = """[{domain}]
user = www-data
group = www-data
listen = /run/php/php{php_version_short}-fpm-{domain}.sock
listen.owner = www-data
listen.group = www-data
pm = dynamic
pm.max_children = 5
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
chdir = {root}
php_admin_value[open_basedir] = {root}/:/tmp/:/usr/share/php/
php_admin_value[disable_functions] = exec,passthru,shell_exec,system,proc_open,popen,curl_exec,curl_multi_exec,parse_ini_file,show_source
"""

def _write_pool(domain: str, root: Path, php_version: str) -> None:
    """Write PHP-FPM pool config for domain."""
    pool_dir = _php_fpm_pool_dir(php_version)
    pool_dir.mkdir(parents=True, exist_ok=True)
    php_version_short = php_version[3:]  # "8.1", "8.2", "8.3"
    conf = POOL_TEMPLATE.format(
        domain=domain,
        root=root,
        php_version_short=php_version_short,
    )
    pool_path(domain, php_version).write_text(conf)

def create_pool(domain: str, php_version: str) -> Path:
    """Create PHP-FPM pool config for domain."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}. Pilihan: {', '.join(PHP_VERSIONS)}")
    
    root = root_path(domain)
    if not root.is_dir():
        raise PhpError(f"Folder root tidak ada: {root}")
    
    if pool_path(domain, php_version).exists():
        raise PhpError(f"Pool {pool_path(domain, php_version)} sudah ada")
    
    _write_pool(domain, root, php_version)
    try:
        php_fpm_test(php_version)
    except PhpError:
        pool_path(domain, php_version).unlink(missing_ok=True)
        raise
    php_fpm_reload(php_version)
    return pool_path(domain, php_version)

def remove_pool(domain: str, php_version: str) -> None:
    """Remove PHP-FPM pool config for domain."""
    pool_file = pool_path(domain, php_version)
    if pool_file.exists():
        pool_file.unlink()
        try:
            php_fpm_test(php_version)
        except PhpError:
            # restore pool file if test fails
            _write_pool(domain, root_path(domain), php_version)
            raise
        php_fpm_reload(php_version)

def set_php_version(domain: str, old_version: str, new_version: str, vhost: Path | None = None) -> None:
    """Change PHP version for a site. Update pool + nginx vhost fastcgi block.

    vhost: path vhost site (dari DB). None = pakai engine aktif.
    Block fastcgi syntax nginx-only — engine apache/litespeed ditolak di server.py.
    """
    root = root_path(domain)
    if not root.is_dir():
        raise PhpError(f"Folder root tidak ada: {root}")

    # hapus block php lama dari vhost dulu (kalau ada)
    remove_php_block(domain, vhost)

    # Remove old pool if not static
    if old_version != "static" and old_version in PHP_VERSIONS:
        remove_pool(domain, old_version)

    # Create new pool if not static
    if new_version != "static" and new_version in PHP_VERSIONS:
        create_pool(domain, new_version)

    # sisip block fastcgi php ke vhost
    if new_version != "static":
        insert_php_block(domain, new_version, vhost)

def _vhost_path(domain: str, vhost: Path | None = None) -> Path:
    return vhost if vhost is not None else webserver_ops.vhost_path(domain)

def remove_php_block(domain: str, vhost: Path | None = None) -> None:
    """Hapus block fastcgi php dari vhost nginx site."""
    vh = _vhost_path(domain, vhost)
    if not vh.exists():
        return
    text = vh.read_text()
    pattern = re.compile(
        rf"\s*{re.escape(PHP_VHOST_BEGIN)}.*?{re.escape(PHP_VHOST_END)}\s*",
        re.DOTALL,
    )
    new_text = pattern.sub("\n", text)
    if new_text != text:
        vh.write_text(new_text)
        try:
            webserver_ops.for_engine("nginx").nginx_test()
        except webserver_ops.WebserverError:
            vh.write_text(text)
            raise

def insert_php_block(domain: str, php_version: str, vhost: Path | None = None) -> None:
    """Sisip block fastcgi php ke vhost nginx site sebelum `location /`."""
    vh = _vhost_path(domain, vhost)
    if not vh.exists():
        raise PhpError(f"vhost {vh} tidak ada")
    text = vh.read_text()
    if PHP_VHOST_BEGIN in text:
        return  # sudah ada block php
    block = _php_location_block(domain, php_version)
    # sisip sebelum location / { ... } paling akhir
    if "location / {" in text:
        text = text.replace("location / {", block + "    location / {", 1)
    else:
        text = text.rstrip() + "\n" + block
    vh.write_text(text)
    try:
        webserver_ops.for_engine("nginx").nginx_test()
    except webserver_ops.WebserverError:
        remove_php_block(domain, vhost)
        raise

def get_pool_status(domain: str) -> dict:
    """Get PHP pool status for all versions."""
    status = {}
    for version in PHP_VERSIONS:
        pool_file = pool_path(domain, version)
        status[version] = pool_file.exists()
    return status


# ==================== PHP INI / EXTENSIONS / POOL OPTIONS ====================

def _php_ini_path(php_version: str) -> Path:
    """Return php.ini path for given PHP version."""
    return PHP_FPM_DIR / php_version / "fpm" / "php.ini"

def _php_mods_dir(php_version: str) -> Path:
    """Return mods-available directory for given PHP version."""
    return PHP_FPM_DIR / php_version / "mods-available"

def _php_fpm_conf_dir(php_version: str) -> Path:
    """Return fpm conf.d directory for given PHP version."""
    return PHP_FPM_DIR / php_version / "fpm" / "conf.d"

def _run_sudo(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run command with sudo if not root. Skip sudo in demo/test mode."""
    # Demo/test mode: CCPANEL_PHP_FPM_DIR points to /tmp/ccp-demo/...
    if os.geteuid() == 0 or str(PHP_FPM_DIR).startswith("/tmp/"):
        return _run(cmd)
    return _run(["sudo", "-n"] + cmd)

def set_ini(php_version: str, key: str, value: str) -> None:
    """Set php.ini value for given PHP version. Reloads FPM."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    ini_path = _php_ini_path(php_version)
    if not ini_path.exists():
        raise PhpError(f"php.ini tidak ditemukan: {ini_path}")
    
    txt = ini_path.read_text()
    # match entire line: key = value (with optional spaces)
    pattern = rf"^\s*{re.escape(key)}\s*=.*$"
    new_line = f"{key} = {value}"
    
    if re.search(pattern, txt, re.M):
        txt = re.sub(pattern, new_line, txt, flags=re.M)
    else:
        # tambah di akhir file
        txt = txt.rstrip() + f"\n{new_line}\n"
    
    # write via sudo if needed
    tmp = Path(f"/tmp/php_ini_{php_version}_{key}.tmp")
    tmp.write_text(txt)
    res = _run_sudo(["cp", str(tmp), str(ini_path)])
    tmp.unlink(missing_ok=True)
    if res.returncode != 0:
        raise PhpError(res.stderr.strip() or f"gagal write {ini_path}")
    
    php_fpm_reload(php_version)

def get_ini(php_version: str) -> dict:
    """Get all php.ini key=value pairs for given PHP version."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    ini_path = _php_ini_path(php_version)
    if not ini_path.exists():
        return {}
    
    txt = ini_path.read_text()
    out = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def get_common_ini_keys() -> list[str]:
    """Return list of commonly configured php.ini keys."""
    return [
        "memory_limit", "max_execution_time", "max_input_time",
        "post_max_size", "upload_max_filesize", "max_file_uploads",
        "disable_functions", "open_basedir", "date.timezone",
        "error_reporting", "display_errors", "log_errors",
        "error_log", "session.save_path", "session.gc_maxlifetime",
        "opcache.enable", "opcache.memory_consumption", "opcache.max_accelerated_files",
        "realpath_cache_size", "realpath_cache_ttl",
    ]

def list_extensions(php_version: str) -> list[dict]:
    """List available extensions for PHP version with enabled status."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    mods_dir = _php_mods_dir(php_version)
    fpm_conf_dir = _php_fpm_conf_dir(php_version)
    
    if not mods_dir.exists():
        return []
    
    exts = []
    for ini_file in mods_dir.glob("*.ini"):
        ext_name = ini_file.stem
        # check if enabled in fpm conf.d (symlink)
        enabled = (fpm_conf_dir / f"20-{ext_name}.ini").exists()
        exts.append({"name": ext_name, "enabled": enabled})
    
    return sorted(exts, key=lambda x: x["name"])

def enable_extension(php_version: str, ext_name: str) -> None:
    """Enable PHP extension for FPM (creates symlink in conf.d)."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    mods_dir = _php_mods_dir(php_version)
    fpm_conf_dir = _php_fpm_conf_dir(php_version)
    
    src = mods_dir / f"{ext_name}.ini"
    if not src.exists():
        raise PhpError(f"Extension {ext_name} tidak ditemukan untuk {php_version}")
    
    fpm_conf_dir.mkdir(parents=True, exist_ok=True)
    dst = fpm_conf_dir / f"20-{ext_name}.ini"
    
    if not dst.exists():
        res = _run_sudo(["ln", "-sf", str(src), str(dst)])
        if res.returncode != 0:
            raise PhpError(res.stderr.strip() or f"gagal enable {ext_name}")
        php_fpm_reload(php_version)

def disable_extension(php_version: str, ext_name: str) -> None:
    """Disable PHP extension for FPM (removes symlink from conf.d)."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    fpm_conf_dir = _php_fpm_conf_dir(php_version)
    dst = fpm_conf_dir / f"20-{ext_name}.ini"
    
    if dst.exists():
        res = _run_sudo(["rm", "-f", str(dst)])
        if res.returncode != 0:
            raise PhpError(res.stderr.strip() or f"gagal disable {ext_name}")
        php_fpm_reload(php_version)

def install_extension(php_version: str, ext_name: str) -> None:
    """Install PHP extension via apt (e.g., php8.3-gd)."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    # map extension name to package name
    pkg_map = {
        "gd": f"{php_version}-gd",
        "curl": f"{php_version}-curl",
        "mbstring": f"{php_version}-mbstring",
        "xml": f"{php_version}-xml",
        "zip": f"{php_version}-zip",
        "mysql": f"{php_version}-mysql",
        "pgsql": f"{php_version}-pgsql",
        "redis": f"{php_version}-redis",
        "imagick": f"{php_version}-imagick",
        "intl": f"{php_version}-intl",
        "bcmath": f"{php_version}-bcmath",
        "soap": f"{php_version}-soap",
        "xdebug": f"{php_version}-xdebug",
        "igbinary": f"{php_version}-igbinary",
        "msgpack": f"{php_version}-msgpack",
    }
    
    pkg = pkg_map.get(ext_name.lower(), f"{php_version}-{ext_name}")
    res = _run_sudo(["apt-get", "update", "-qq"])
    res = _run_sudo(["apt-get", "install", "-y", pkg])
    if res.returncode != 0:
        raise PhpError(res.stderr.strip() or f"gagal install {pkg}")
    
    # auto-enable after install
    enable_extension(php_version, ext_name)

def set_pool_option(domain: str, php_version: str, key: str, value: str) -> None:
    """Set PHP-FPM pool option for a domain. Reloads FPM."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    pool_file = pool_path(domain, php_version)
    if not pool_file.exists():
        raise PhpError(f"Pool tidak ditemukan: {pool_file}")
    
    txt = pool_file.read_text()
    # match entire line: key = value (with optional spaces)
    pattern = rf"^\s*{re.escape(key)}\s*=.*$"
    new_line = f"{key} = {value}"
    
    if re.search(pattern, txt, re.M):
        txt = re.sub(pattern, new_line, txt, flags=re.M)
    else:
        # tambah sebelum penutup ]
        txt = txt.rstrip() + f"\n{new_line}\n"
    
    tmp = Path(f"/tmp/pool_{domain}_{php_version}_{key}.tmp")
    tmp.write_text(txt)
    res = _run_sudo(["cp", str(tmp), str(pool_file)])
    tmp.unlink(missing_ok=True)
    if res.returncode != 0:
        raise PhpError(res.stderr.strip() or f"gagal write {pool_file}")
    
    php_fpm_reload(php_version)

def get_pool_options(domain: str, php_version: str) -> dict:
    """Get all pool options for a domain."""
    if php_version not in PHP_VERSIONS:
        raise PhpError(f"PHP version tidak valid: {php_version}")
    
    pool_file = pool_path(domain, php_version)
    if not pool_file.exists():
        return {}
    
    txt = pool_file.read_text()
    out = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def get_common_pool_keys() -> list[str]:
    """Return list of commonly configured pool options."""
    return [
        "pm.max_children", "pm.start_servers", "pm.min_spare_servers",
        "pm.max_spare_servers", "pm.max_requests", "request_terminate_timeout",
        "request_slowlog_timeout", "slowlog", "rlimit_files", "rlimit_core",
        "chdir", "catch_workers_output", "clear_env",
        "security.limit_extensions",
    ]