"""Admin MongoDB: status, config (YAML), log, DB list.

MongoDB tak punya konsep GRANT per-DB ala SQL — auth global via roles.
Config YAML /etc/mongod.conf (CCPANEL_MONGO_CONF). Log ke journald
(unit mongod) atau file log dari config. Semua baca via subprocess
argumen-list; TIDAK menulis config otomatis (YAML rapuh) — hanya baca +
log viewer + optimasi terbatas lewat mongosh setParameter kalau ada.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MONGO_HOST = os.environ.get("CCPANEL_MONGO_HOST", "127.0.0.1")
MONGO_PORT = os.environ.get("CCPANEL_MONGO_PORT", "27017")
MONGO_CONF = Path(os.environ.get("CCPANEL_MONGO_CONF", "/etc/mongod.conf"))
MONGO_BIN = os.environ.get("CCPANEL_MONGO_BIN", "mongosh")

class MongoAdminError(Exception):
    pass


def _mongosh(js: str) -> str:
    """Jalankan mongosh --eval. Return stdout. Butuh auth kalau diaktifkan."""
    cmd = [MONGO_BIN, "--quiet", "--host", MONGO_HOST, "--port", MONGO_PORT, "--eval", js]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        raise MongoAdminError(res.stderr.strip() or res.stdout.strip() or "mongosh failed")
    return res.stdout.strip()


def available() -> dict:
    """Deteksi mongod: jalan? mongosh ada? config ada?"""
    info = {
        "mongosh": MONGO_BIN,
        "config": str(MONGO_CONF) if MONGO_CONF.exists() else "",
        "unit": "mongod",
        "running": False,
        "version": "",
    }
    try:
        out = _mongosh("db.runCommand({ buildInfo: 1 }).version")
        m = re.search(r"[\w.]+", out)
        info["version"] = m.group(0) if m else out
        info["running"] = True
    except MongoAdminError:
        pass
    return info


# ---------- status ----------

def get_status() -> dict:
    """Status server: buildInfo, koneksi, DB list + ukuran."""
    try:
        build = _mongosh("JSON.stringify(db.runCommand({ buildInfo: 1 }))")
    except MongoAdminError:
        build = ""
    dbs = []
    try:
        out = _mongosh(
            "db.adminCommand('listDatabases').databases"
            ".map(d => ({ name: d.name, sizeOnDisk: d.sizeOnDisk, empty: d.empty }))"
        )
        # mongosh output: [{...}] atau error
        m = re.findall(r"\{[^{}]*\}", out)
        for item in m[:50]:
            name = re.search(r"name:\s*'([^']+)'", item) or re.search(r'name:\s*"([^"]+)"', item)
            size = re.search(r"sizeOnDisk:\s*(\d+)", item)
            if name:
                dbs.append({
                    "name": name.group(1),
                    "size": int(size.group(1)) if size else 0,
                })
    except MongoAdminError:
        pass
    conns = ""
    try:
        conns = _mongosh("db.serverStatus().connections.current")
    except MongoAdminError:
        pass
    return {"build": build, "dbs": dbs, "connections": conns}


# ---------- config (YAML, baca saja + log path) ----------

def read_config() -> dict:
    """Baca /etc/mongod.conf (YAML) + ekstrak systemLog.path kalau ada."""
    if not MONGO_CONF.exists():
        return {"content": "", "log_path": "", "config": str(MONGO_CONF)}
    content = MONGO_CONF.read_text(encoding="utf-8", errors="replace")
    log_path = ""
    m = re.search(r"^\s*path:\s*(\S+)", content, re.MULTILINE)
    if m:
        log_path = m.group(1)
    return {"content": content, "log_path": log_path, "config": str(MONGO_CONF)}


# ---------- log ----------

def read_journal(lines: int) -> list[str]:
    try:
        res = subprocess.run(
            ["journalctl", "-u", "mongod", "--no-pager", "-n", str(lines)],
            capture_output=True, text=True, timeout=10,
        )
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (subprocess.TimeoutExpired, OSError):
        return []


def read_log_file(lines: int) -> list[str]:
    """Tail file log dari config (systemLog.path)."""
    log_path = read_config().get("log_path", "")
    if not log_path or not Path(log_path).exists():
        return []
    try:
        res = subprocess.run(["tail", "-n", str(lines), log_path], capture_output=True, text=True, timeout=10)
        return res.stdout.strip().splitlines() if res.returncode == 0 else []
    except (subprocess.TimeoutExpired, OSError):
        return []


def get_logs(lines: int = 200) -> dict:
    return {
        "available": available(),
        "journal": read_journal(lines),
        "file": read_log_file(lines),
    }


# ---------- optimasi terbatas ----------

# variable runtime mongod yang bisa diubah via setParameter (butuh restart utk sebagian)
RUNTIME_PARAMS = {
    "maxIncomingConnections": "number",
    "cursorTimeoutMillis": "number",
    "logLevel": "number",
}

def set_parameter(name: str, value: str) -> None:
    """setParameter runtime — kalau mongod mengizinkan (butuh auth admin)."""
    if name not in RUNTIME_PARAMS:
        raise MongoAdminError(f"parameter tidak diizinkan: {name}")
    if not re.fullmatch(r"\d+", value.strip()):
        raise MongoAdminError("nilai harus angka bulat")
    _mongosh(f"db.adminCommand({{ setParameter: 1, {name}: {value.strip()} }})")
