"""Admin PostgreSQL: variable, config, optimasi, log.

Config Debian: /etc/postgresql/<ver>/<cluster>/postgresql.conf + include_dir 'conf.d'.
Override ditulis ke conf.d/99-ccpanel.conf (tak sentuh file utama).
SET GLOBAL analog: ALTER SYSTEM (postgresql.auto.conf) + pg_reload_conf().
Semua via subprocess argumen-list (tanpa shell=True).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

PG_HOST = os.environ.get("CCPANEL_PG_HOST", "localhost")
PG_PORT = os.environ.get("CCPANEL_PG_PORT", "5432")
PG_USER = os.environ.get("CCPANEL_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("CCPANEL_PG_PASSWORD", "")
CONF_BASE = Path(os.environ.get("CCPANEL_PG_CONF_DIR", "/etc/postgresql"))

# variable yang aman diubah runtime via ALTER SYSTEM + reload (context user/sighup).
# tipe: number/size/float/onoff/string
GLOBAL_VARS = {
    "max_connections": "number",
    "shared_buffers": "size",
    "work_mem": "size",
    "maintenance_work_mem": "size",
    "effective_cache_size": "size",
    "wal_buffers": "size",
    "max_wal_size": "size",
    "checkpoint_completion_target": "float",
    "random_page_cost": "float",
    "autovacuum": "onoff",
    "synchronous_commit": "onoff",
    "log_min_duration_statement": "number",
    "statement_timeout": "number",
}

OPTIMIZATION_PRESETS = {
    "low": {
        "max_connections": "50",
        "shared_buffers": "128MB",
        "work_mem": "4MB",
        "maintenance_work_mem": "64MB",
        "effective_cache_size": "384MB",
        "max_wal_size": "1GB",
    },
    "medium": {
        "max_connections": "100",
        "shared_buffers": "256MB",
        "work_mem": "8MB",
        "maintenance_work_mem": "128MB",
        "effective_cache_size": "768MB",
        "max_wal_size": "2GB",
    },
    "high": {
        "max_connections": "200",
        "shared_buffers": "512MB",
        "work_mem": "16MB",
        "maintenance_work_mem": "256MB",
        "effective_cache_size": "1.5GB",
        "max_wal_size": "4GB",
    },
}

class PgAdminError(Exception):
    pass


def _env() -> dict:
    env = os.environ.copy()
    if PG_PASSWORD:
        env["PGPASSWORD"] = PG_PASSWORD
    return env


def _psql(sql: str, tuples_only: bool = True) -> list[str]:
    cmd = ["psql", f"--host={PG_HOST}", f"--port={PG_PORT}", f"--username={PG_USER}",
           "--no-align", "--tuples-only", "--field-separator=|", "--command", sql]
    res = subprocess.run(cmd, capture_output=True, text=True, env=_env())
    if res.returncode != 0:
        raise PgAdminError(res.stderr.strip() or res.stdout.strip() or "psql failed")
    return [l for l in res.stdout.splitlines() if l.strip()]


def _cluster_dir() -> Path:
    """Cari dir cluster aktif pertama: /etc/postgresql/<ver>/<cluster>/."""
    if not CONF_BASE.is_dir():
        raise PgAdminError(f"dir config postgresql tidak ada: {CONF_BASE}")
    for ver in sorted(CONF_BASE.iterdir(), reverse=True):
        for cluster in sorted(ver.iterdir()):
            return cluster
    raise PgAdminError("tidak ada cluster postgresql ditemukan")


# ---------- variable ----------

def get_variables() -> dict:
    """Nilai variable dari pg_settings + status koneksi dasar."""
    names = ", ".join(f"'{n}'" for n in GLOBAL_VARS)
    rows = _psql(
        f"SELECT name, setting, unit FROM pg_settings WHERE name IN ({names}) ORDER BY name"
    )
    vars_ = {}
    for line in rows:
        parts = line.split("|")
        if len(parts) >= 2:
            name, setting = parts[0], parts[1]
            unit = parts[2] if len(parts) > 2 else ""
            vars_[name] = f"{setting}{unit or ''}".strip()
    # status singkat: koneksi, ukuran DB
    try:
        conns = _psql("SELECT count(*) FROM pg_stat_activity")
        dbcount = _psql("SELECT count(*) FROM pg_database WHERE datallowconn")
        status = {"connections": conns[0] if conns else "?", "databases": dbcount[0] if dbcount else "?"}
    except PgAdminError:
        status = {}
    return {"variables": vars_, "status": status}


def set_global(variable: str, value: str) -> None:
    """ALTER SYSTEM + reload. Berlaku permanen (postgresql.auto.conf)."""
    if variable not in GLOBAL_VARS:
        raise PgAdminError(f"variable tidak diizinkan: {variable}")
    vtype = GLOBAL_VARS[variable]
    if vtype == "onoff":
        if value not in ("on", "off", "true", "false"):
            raise PgAdminError("nilai harus on/off")
        safe = value
    elif vtype == "float":
        if not re.fullmatch(r"\d+(\.\d+)?", value.strip()):
            raise PgAdminError("nilai harus angka desimal")
        safe = value.strip()
    elif vtype == "size":
        if not re.fullmatch(r"\d+(\.\d+)?[kKmMgGtT]?[bB]?", value.strip()):
            raise PgAdminError("nilai harus angka, boleh suffix k/M/G + B")
        safe = value.strip().upper()
    else:  # number
        if not re.fullmatch(r"\d+", value.strip()):
            raise PgAdminError("nilai harus angka bulat")
        safe = value.strip()
    _psql(f"ALTER SYSTEM SET {variable} = '{safe}'; SELECT pg_reload_conf();")


def apply_preset(name: str) -> dict:
    """Terapkan preset → tulis conf.d/99-ccpanel.conf + ALTER SYSTEM. Restart untuk static."""
    if name not in OPTIMIZATION_PRESETS:
        raise PgAdminError(f"preset tidak dikenal: {name}")
    conf = OPTIMIZATION_PRESETS[name]
    cluster = _cluster_dir()
    conf_dir = cluster / "conf.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# CCPanel auto-optimization"]
    for k, v in conf.items():
        lines.append(f"{k} = {v}")
    override = conf_dir / "99-ccpanel.conf"
    override.write_text("\n".join(lines) + "\n", encoding="utf-8")
    applied = {}
    for k, v in conf.items():
        try:
            set_global(k, v)
            applied[k] = "runtime"
        except PgAdminError:
            applied[k] = "perlu-restart"
    return {"preset": name, "written": str(override), "applied": applied}


# ---------- config ----------

def read_config() -> dict:
    """Baca postgresql.conf utama + override + daftar conf.d."""
    cluster = _cluster_dir()
    main = cluster / "postgresql.conf"
    conf_dir = cluster / "conf.d"
    files = []
    if main.exists():
        files.append({"path": str(main), "content": main.read_text(encoding="utf-8", errors="replace")})
    if conf_dir.is_dir():
        for p in sorted(conf_dir.glob("*.conf")):
            files.append({"path": str(p), "content": p.read_text(encoding="utf-8", errors="replace")})
    override_path = conf_dir / "99-ccpanel.conf"
    override = override_path.read_text(encoding="utf-8", errors="replace") if override_path.exists() else ""
    return {"files": files, "override": override, "override_path": str(override_path)}


def write_config(content: str) -> None:
    """Tulis ulang conf.d/99-ccpanel.conf. Restart dibutuhkan."""
    if len(content) > 64 * 1024:
        raise PgAdminError("config terlalu besar")
    cluster = _cluster_dir()
    conf_dir = cluster / "conf.d"
    conf_dir.mkdir(parents=True, exist_ok=True)
    (conf_dir / "99-ccpanel.conf").write_text(content, encoding="utf-8")


# ---------- log ----------

def log_available() -> dict:
    """Info: log dir, journal unit, variable logging."""
    info = {"journal": "", "log_dir": "", "log_min_duration": "", "log_connections": ""}
    try:
        rows = _psql("SELECT name, setting FROM pg_settings WHERE name IN ('log_min_duration_statement','log_connections')")
        for line in rows:
            parts = line.split("|")
            if len(parts) == 2:
                info[parts[0]] = parts[1]
    except PgAdminError:
        pass
    try:
        cluster = _cluster_dir()
        log_dir = cluster / "log"
        info["log_dir"] = str(log_dir) if log_dir.is_dir() else ""
        ver = cluster.parent.name
        info["journal"] = f"postgresql@{ver}-{cluster.name}"
    except PgAdminError:
        pass
    return info


def _tail(path: str, lines: int) -> list[str]:
    if not path or not Path(path).exists():
        return []
    try:
        res = subprocess.run(["tail", "-n", str(lines), path], capture_output=True, text=True, timeout=10)
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (subprocess.TimeoutExpired, OSError):
        return []


def read_journal(lines: int) -> list[str]:
    unit = log_available().get("journal", "")
    if not unit:
        return []
    try:
        res = subprocess.run(
            ["journalctl", "-u", unit, "--no-pager", "-n", str(lines)],
            capture_output=True, text=True, timeout=10,
        )
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (subprocess.TimeoutExpired, OSError):
        return []


def read_server_log(lines: int) -> list[str]:
    """Tail file log postgres (kalau logging_collector aktif)."""
    try:
        log_dir = log_available().get("log_dir", "")
        if not log_dir:
            return []
        newest = sorted(Path(log_dir).glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not newest:
            return []
        return _tail(str(newest[0]), lines)
    except (PgAdminError, OSError):
        return []
