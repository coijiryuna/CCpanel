"""Admin MySQL/MariaDB: baca/tulis config, status variabel, optimasi, log.

Config: /etc/mysql/mariadb.conf.d/ (debian). File 50-server.cnf berisi
[mysqld] section — variable diubah lewat file override terpisah
CCPANEL_MYSQL_CONF (default /etc/mysql/mariadb.conf.d/99-ccpanel.cnf)
agar tidak menyentuh file vendor. Semua via subprocess argumen-list.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MYSQL_HOST = os.environ.get("CCPANEL_MYSQL_HOST", "localhost")
MYSQL_ROOT_PASSWORD = os.environ.get("CCPANEL_MYSQL_ROOT_PASSWORD", "")
CONF_PATH = Path(os.environ.get("CCPANEL_MYSQL_CONF", "/etc/mysql/mariadb.conf.d/99-ccpanel.cnf"))

# variable mana yang aman diubah via SET GLOBAL (tanpa restart), plus tipe value
# (number/size/onoff/string). Hanya yang lazim dioptimasi.
GLOBAL_VARS = {
    "max_connections": "number",
    "innodb_buffer_pool_size": "size",
    "innodb_log_file_size": "size",
    "innodb_flush_log_at_trx_commit": "number",
    "query_cache_size": "size",
    "tmp_table_size": "size",
    "max_heap_table_size": "size",
    "sort_buffer_size": "size",
    "join_buffer_size": "size",
    "read_buffer_size": "size",
    "thread_cache_size": "number",
    "table_open_cache": "number",
    "key_buffer_size": "size",
    "slow_query_log": "onoff",
    "long_query_time": "number",
}

# presets optimasi: nama → dict variable → value (string, siap tulis ke file)
OPTIMIZATION_PRESETS = {
    "low": {
        "max_connections": "50",
        "innodb_buffer_pool_size": "128M",
        "thread_cache_size": "8",
        "tmp_table_size": "16M",
        "max_heap_table_size": "16M",
    },
    "medium": {
        "max_connections": "100",
        "innodb_buffer_pool_size": "256M",
        "thread_cache_size": "16",
        "tmp_table_size": "32M",
        "max_heap_table_size": "32M",
    },
    "high": {
        "max_connections": "200",
        "innodb_buffer_pool_size": "512M",
        "thread_cache_size": "32",
        "tmp_table_size": "64M",
        "max_heap_table_size": "64M",
    },
}

class MysqlAdminError(Exception):
    pass


def _mysql(sql: str) -> list[dict]:
    cmd = ["mysql", f"--host={MYSQL_HOST}", "--user=root", "--batch", "--skip-column-names"]
    if MYSQL_ROOT_PASSWORD:
        cmd.append(f"--password={MYSQL_ROOT_PASSWORD}")
    cmd.append(f"--execute={sql}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise MysqlAdminError(res.stderr.strip() or res.stdout.strip() or "mysql failed")
    # baris: TAB-separated; kosong → []
    return [line.split("\t") for line in res.stdout.strip().splitlines()] if res.stdout.strip() else []


# ---------- variabel status / global ----------

def get_variables() -> dict:
    """Semua variable GLOBAL + STATUS yang dikenal, plus nilai saat ini."""
    rows = _mysql("SHOW GLOBAL VARIABLES")
    globals_ = {k: v for k, v in rows}
    rows = _mysql("SHOW GLOBAL STATUS")
    status = {k: v for k, v in rows}
    known = {k: globals_.get(k, "") for k in GLOBAL_VARS}
    return {"variables": known, "status": status, "globals": globals_}


def set_global(variable: str, value: str) -> None:
    """SET GLOBAL — berlaku runtime, hilang setelah restart."""
    if variable not in GLOBAL_VARS:
        raise MysqlAdminError(f"variable tidak diizinkan: {variable}")
    vtype = GLOBAL_VARS[variable]
    if vtype == "onoff":
        if value not in ("ON", "OFF"):
            raise MysqlAdminError("nilai harus ON/OFF")
        safe = value
    else:
        if not re.fullmatch(r"\d+[KMG]?", value.strip().upper()):
            raise MysqlAdminError("nilai harus angka, boleh suffix K/M/G")
        safe = value.strip().upper()
    _mysql(f"SET GLOBAL {variable} = {safe}")


def apply_preset(name: str) -> dict:
    """Terapkan preset optimasi → tulis file config + SET GLOBAL. Restart dibutuhkan utk yang static."""
    if name not in OPTIMIZATION_PRESETS:
        raise MysqlAdminError(f"preset tidak dikenal: {name}")
    conf = OPTIMIZATION_PRESETS[name]
    CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# CCPanel auto-optimization", "[mysqld]"]
    for k, v in conf.items():
        lines.append(f"{k} = {v}")
    CONF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    applied = {}
    for k, v in conf.items():
        try:
            set_global(k, v)
            applied[k] = "runtime"
        except MysqlAdminError:
            applied[k] = "perlu-restart"
    return {"preset": name, "written": str(CONF_PATH), "applied": applied}


def read_config() -> dict:
    """Baca config saat ini: [mysqld] section dari semua file + override file."""
    files = []
    for p in sorted(Path("/etc/mysql/mariadb.conf.d").glob("*.cnf")):
        try:
            files.append({"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")})
        except OSError:
            continue
    override = CONF_PATH.read_text(encoding="utf-8", errors="replace") if CONF_PATH.exists() else ""
    return {"files": files, "override": override, "override_path": str(CONF_PATH)}


def write_config(content: str) -> None:
    """Tulis ulang file override 99-ccpanel.cnf."""
    if len(content) > 64 * 1024:
        raise MysqlAdminError("config terlalu besar")
    CONF_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONF_PATH.write_text(content, encoding="utf-8")


# ---------- log ----------

def log_available() -> dict:
    """Deteksi lokasi log: error log (journald/mysql), slow query, general log."""
    info = {}
    try:
        rows = _mysql("SHOW VARIABLES LIKE 'log_error'")
        info["error_log"] = rows[0][1] if rows else ""
    except MysqlAdminError:
        info["error_log"] = ""
    try:
        rows = _mysql("SHOW VARIABLES LIKE 'slow_query_log_file'")
        info["slow_log"] = rows[0][1] if rows else ""
        rows = _mysql("SHOW VARIABLES LIKE 'slow_query_log'")
        info["slow_enabled"] = (rows[0][1] if rows else "OFF") == "ON"
    except MysqlAdminError:
        info["slow_log"], info["slow_enabled"] = "", False
    info["journal"] = "mariadb"  # systemd unit; bisa diganti
    return info


def read_error_log(lines: int = 200) -> list[str]:
    """Error log via journalctl (systemd mariadb). Kalau gagal → []."""
    try:
        res = subprocess.run(
            ["journalctl", "-u", "mariadb", "--no-pager", "-n", str(lines)],
            capture_output=True, text=True, timeout=10,
        )
        if res.returncode != 0:
            return []
        return res.stdout.strip().splitlines()
    except (subprocess.TimeoutExpired, OSError):
        return []


def read_slow_log(lines: int = 200) -> list[str]:
    """Tail slow query log file (kalau ada & enabled)."""
    try:
        rows = _mysql("SHOW VARIABLES LIKE 'slow_query_log_file'")
        path = rows[0][1] if rows else ""
        if not path or not Path(path).exists():
            return []
        res = subprocess.run(["tail", "-n", str(lines), path], capture_output=True, text=True, timeout=10)
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (MysqlAdminError, subprocess.TimeoutExpired, OSError):
        return []


def read_general_log(lines: int = 200) -> list[str]:
    """Tail general log (semua query). Kosong kalau tak enabled."""
    try:
        rows = _mysql("SHOW VARIABLES LIKE 'general_log_file'")
        path = rows[0][1] if rows else ""
        if not path or not Path(path).exists():
            return []
        res = subprocess.run(["tail", "-n", str(lines), path], capture_output=True, text=True, timeout=10)
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (MysqlAdminError, subprocess.TimeoutExpired, OSError):
        return []
