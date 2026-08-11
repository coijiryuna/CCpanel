"""App Store: katalog runtime + aplikasi pendukung server, deteksi status,
install/uninstall. Semua perintah via subprocess argumen-list (tanpa shell).

Katalog bisa dinamis: fetch JSON dari URL remote (misal raw GitHub), cache
lokal dengan TTL, fallback ke katalog statis bawaan kalau offline/gagal.

Kategori:
  php    — versi PHP-FPM (7.4, 8.0, 8.1, 8.2, 8.3)
  node   — Node.js via nvm (v18, v20, v22, v24)
  go     — Go SDK (1.22, 1.23, 1.24)
  app    — aplikasi pendukung (nginx, apache, openlitespeed, mysql, redis, git, composer, pm2, docker, certbot)

Env override utk testing:
  CCPANEL_APPSTORE_URL    URL JSON katalog remote (default None = pakai statis)
  CCPANEL_APPSTORE_CACHE  path file cache (default /var/cache/ccpanel-appstore.json)
  CCPANEL_APPSTORE_TTL    detik cache valid (default 3600)
  CCPANEL_APT / CCPANEL_NVM_DIR / CCPANEL_GO_ROOT / CCPANEL_APPSTORE_LOG
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

# env override utk testing (mirip pola core lain)
APT = os.environ.get("CCPANEL_APT", "apt-get")
NVM_DIR = Path(os.environ.get("CCPANEL_NVM_DIR", os.path.expanduser("~/.nvm")))
GO_ROOT = Path(os.environ.get("CCPANEL_GO_ROOT", "/usr/local/go"))
APPSTORE_LOG = Path(os.environ.get("CCPANEL_APPSTORE_LOG", "/var/log/ccpanel-appstore.log"))
APPSTORE_URL = os.environ.get("CCPANEL_APPSTORE_URL") or None
APPSTORE_CACHE = Path(os.environ.get("CCPANEL_APPSTORE_CACHE", "/var/cache/ccpanel-appstore.json"))
APPSTORE_TTL = int(os.environ.get("CCPANEL_APPSTORE_TTL", "3600"))
SYSTEMCTL = os.environ.get("CCPANEL_SYSTEMCTL", "systemctl")
SERVICE_ACTIONS = {"start", "stop", "restart", "reload"}

# ------------------------------------------------------------------ task async
# Task install/uninstall jalan di background thread. Frontend polling status
# + output per baris (tail). Status: running / done / error.
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()

def _task(key: str) -> dict:
    with _TASKS_LOCK:
        t = _TASKS.setdefault(key, {"status": "running", "lines": [], "error": "", "done": False})
    return t

def _task_append(key: str, line: str) -> None:
    with _TASKS_LOCK:
        t = _TASKS.setdefault(key, {"status": "running", "lines": [], "error": "", "done": False})
        t["lines"].append(line)
        if len(t["lines"]) > 2000:
            t["lines"] = t["lines"][-2000:]

def _task_finish(key: str, ok: bool, error: str = "") -> None:
    with _TASKS_LOCK:
        t = _TASKS.setdefault(key, {"status": "running", "lines": [], "error": "", "done": False})
        t["status"] = "done" if ok else "error"
        t["error"] = error
        t["done"] = True

def _run_stream(cmd: list[str], key: str, timeout: int = 1800) -> None:
    """Jalankan command, stream output baris per baris ke task key."""
    _task_append(key, f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1,
        )
    except Exception as e:
        _task_finish(key, False, str(e))
        return
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line:
                _task_append(key, line)
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        _task_finish(key, False, f"Timeout ({timeout}s)")
        return
    _task_finish(key, rc == 0, "" if rc == 0 else f"exit code {rc}")

def _stream_worker(item: dict, action: str, key: str) -> None:
    """Worker thread: jalankan install/uninstall item, stream ke task."""
    try:
        cmd = item[action]
    except KeyError:
        _task_finish(key, False, f"{action} tidak ada untuk {item.get('id', '?')}")
        return
    _run_stream(cmd, key)
    with _TASKS_LOCK:
        ok = _TASKS.get(key, {}).get("status") == "done"
    if action == "install" and ok:
        _log_install(item.get("id", "?"), "install", None)

def start_task(item_id: str, action: str) -> dict:
    """Mulai install/uninstall async. Return task key."""
    item = _find(item_id)
    if action == "install" and _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} sudah terinstall")
    if action == "uninstall" and not _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} tidak terinstall")
    key = f"{item_id}:{action}:{int(time.time())}"
    t = threading.Thread(target=_stream_worker, args=(item, action, key), daemon=True)
    t.start()
    return {"ok": True, "id": item_id, "action": action, "key": key}

def task_status(key: str) -> dict:
    """Status task + output. Frontend polling."""
    with _TASKS_LOCK:
        t = _TASKS.get(key)
        if t is None:
            return {"status": "done", "lines": [], "error": "task not found", "done": True}
        return dict(t)

def task_list() -> list[dict]:
    """Semua task (belum selesai saja)."""
    with _TASKS_LOCK:
        return [
            {"key": k, "status": v["status"], "done": v["done"]}
            for k, v in _TASKS.items() if not v["done"]
        ]

# id unik + command list-of-str + detect data-driven (bukan lambda) supaya
# bisa diserialisasi ke JSON remote.
CATALOG: list[dict] = [
    # ---- PHP ----
    {"id": "php7.4", "name": "PHP 7.4", "category": "php", "desc": "PHP-FPM 7.4 (legacy)",
     "install": [APT, "install", "-y", "php7.4-fpm"], "uninstall": [APT, "remove", "-y", "php7.4-fpm"],
     "detect": {"type": "which", "bin": ["php7.4", "php-fpm7.4"]}, "service": "php7.4-fpm"},
    {"id": "php8.0", "name": "PHP 8.0", "category": "php", "desc": "PHP-FPM 8.0",
     "install": [APT, "install", "-y", "php8.0-fpm"], "uninstall": [APT, "remove", "-y", "php8.0-fpm"],
     "detect": {"type": "which", "bin": ["php8.0", "php-fpm8.0"]}, "service": "php8.0-fpm"},
    {"id": "php8.1", "name": "PHP 8.1", "category": "php", "desc": "PHP-FPM 8.1",
     "install": [APT, "install", "-y", "php8.1-fpm"], "uninstall": [APT, "remove", "-y", "php8.1-fpm"],
     "detect": {"type": "which", "bin": ["php8.1", "php-fpm8.1"]}, "service": "php8.1-fpm"},
    {"id": "php8.2", "name": "PHP 8.2", "category": "php", "desc": "PHP-FPM 8.2",
     "install": [APT, "install", "-y", "php8.2-fpm"], "uninstall": [APT, "remove", "-y", "php8.2-fpm"],
     "detect": {"type": "which", "bin": ["php8.2", "php-fpm8.2"]}, "service": "php8.2-fpm"},
    {"id": "php8.3", "name": "PHP 8.3", "category": "php", "desc": "PHP-FPM 8.3",
     "install": [APT, "install", "-y", "php8.3-fpm"], "uninstall": [APT, "remove", "-y", "php8.3-fpm"],
     "detect": {"type": "which", "bin": ["php8.3", "php-fpm8.3"]}, "service": "php8.3-fpm"},
    {"id": "php8.4", "name": "PHP 8.4", "category": "php", "desc": "PHP-FPM 8.4 (Debian 13/trixie)",
     "install": [APT, "install", "-y", "php8.4-fpm"], "uninstall": [APT, "remove", "-y", "php8.4-fpm"],
     "detect": {"type": "which", "bin": ["php8.4", "php-fpm8.4"]}, "service": "php8.4-fpm"},
    # ---- Node (nvm) ----
    {"id": "node18", "name": "Node.js 18", "category": "node", "desc": "Node.js v18 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 18"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 18"],
     "detect": {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v18")}},
    {"id": "node20", "name": "Node.js 20", "category": "node", "desc": "Node.js v20 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 20"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 20"],
     "detect": {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v20")}},
    {"id": "node22", "name": "Node.js 22", "category": "node", "desc": "Node.js v22 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 22"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 22"],
     "detect": {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v22")}},
    {"id": "node24", "name": "Node.js 24", "category": "node", "desc": "Node.js v24 via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 24"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 24"],
     "detect": {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v24")}},
    # ---- Go SDK ----
    {"id": "go1.22", "name": "Go 1.22", "category": "go", "desc": "Go SDK 1.22",
     "install": ["bash", "-lc", f"curl -sSL https://go.dev/dl/go1.22.linux-amd64.tar.gz | tar -C {GO_ROOT} -xzf - && mv {GO_ROOT}/go {GO_ROOT}/go1.22"],
     "uninstall": ["rm", "-rf", str(GO_ROOT / "go1.22")],
     "detect": {"type": "dir", "path": str(GO_ROOT / "go1.22")}},
    {"id": "go1.23", "name": "Go 1.23", "category": "go", "desc": "Go SDK 1.23",
     "install": ["bash", "-lc", f"wget -qO- https://go.dev/dl/go1.23.linux-amd64.tar.gz | tar -C {GO_ROOT} -xzf && mv {GO_ROOT}/go {GO_ROOT}/go1.23"],
     "uninstall": ["rm", "-rf", str(GO_ROOT / "go1.23")],
     "detect": {"type": "dir", "path": str(GO_ROOT / "go1.23")}},
    {"id": "go1.24", "name": "Go 1.24", "category": "go", "desc": "Go SDK 1.24",
     "install": ["bash", "-lc", f"wget -qO- https://go.dev/dl/go1.24.linux-amd64.tar.gz | tar -C {GO_ROOT} -xz && mv {GO_ROOT}/go {GO_ROOT}/go1.24"],
     "uninstall": ["rm", "-rf", str(GO_ROOT / "go1.24")],
     "detect": {"type": "dir", "path": str(GO_ROOT / "go1.24")}},
    # ---- Aplikasi pendukung ----
    {"id": "nginx", "name": "Nginx", "category": "app", "desc": "Web server / reverse proxy",
     "install": [APT, "install", "-y", "nginx"], "uninstall": [APT, "remove", "-y", "nginx"],
     "detect": {"type": "which", "bin": ["nginx"]}, "service": "nginx"},
    {"id": "apache", "name": "Apache", "category": "app", "desc": "Apache HTTP Server (apache2)",
     "install": [APT, "install", "-y", "apache2"], "uninstall": [APT, "remove", "-y", "apache2"],
     "detect": {"type": "which", "bin": ["apache2", "apache2ctl", "httpd"]}, "service": "apache2"},
    {"id": "openlitespeed", "name": "OpenLiteSpeed", "category": "app", "desc": "LiteSpeed web server (lshttpd)",
     "install": ["bash", "-lc", "curl -fsSL https://repo.litespeed.sh | bash && apt-get install -y openlitespeed"],
     "uninstall": ["bash", "-lc", "apt-get remove -y openlitespeed"],
     "detect": {"type": "which", "bin": ["lshttpd", "litespeed"]}, "service": "lsws"},
    {"id": "mariadb", "name": "MariaDB", "category": "app", "desc": "Database server",
     "install": [APT, "install", "-y", "mariadb-server"], "uninstall": [APT, "remove", "-y", "mariadb-server"],
     "detect": {"type": "which", "bin": ["mysql", "mariadb"]}, "service": "mariadb"},
    {"id": "redis", "name": "Redis", "category": "app", "desc": "In-memory key-value store",
     "install": [APT, "install", "-y", "redis-server"], "uninstall": [APT, "remove", "-y", "redis-server"],
     "detect": {"type": "which", "bin": ["redis-server"]}, "service": "redis-server"},
    {"id": "postgresql", "name": "PostgreSQL", "category": "app", "desc": "Relational database",
     "install": [APT, "install", "-y", "postgresql"], "uninstall": [APT, "remove", "-y", "postgresql"],
     "detect": {"type": "which", "bin": ["psql"]}, "service": "postgresql"},
    {"id": "composer", "name": "Composer", "category": "app", "desc": "PHP dependency manager",
     "install": ["bash", "-lc", "curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer"],
     "uninstall": ["rm", "-f", "/usr/local/bin/composer"],
     "detect": {"type": "which", "bin": ["composer"]}},
    {"id": "pm2", "name": "PM2", "category": "app", "desc": "Node.js process manager",
     "install": ["bash", "-lc", "npm install -g pm2"], "uninstall": ["bash", "-lc", "npm uninstall -g pm2"],
     "detect": {"type": "which", "bin": ["pm2"]}},
    {"id": "certbot", "name": "Certbot", "category": "app", "desc": "SSL certificate automation",
     "install": [APT, "install", "-y", "certbot", "python3-certbot-nginx"],
     "uninstall": [APT, "remove", "-y", "certbot"],
     "detect": {"type": "which", "bin": ["certbot"]}},
    {"id": "git", "name": "Git", "category": "app", "desc": "Version control",
     "install": [APT, "install", "-y", "git"], "uninstall": [APT, "remove", "-y", "git"],
     "detect": {"type": "which", "bin": ["git"]}},
    {"id": "docker", "name": "Docker", "category": "app", "desc": "Container runtime (docker.io)",
     "install": [APT, "install", "-y", "docker.io"], "uninstall": [APT, "remove", "-y", "docker.io"],
     "detect": {"type": "which", "bin": ["docker"]}, "service": "docker"},
]


class AppStoreError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AppStoreError(f"Timeout: {' '.join(cmd)}") from e


def _which(bin_name: str) -> bool:
    return shutil.which(bin_name) is not None


def _detect(spec) -> bool:
    """Evaluasi spec detect data-driven. Unknown type → False (aman)."""
    if not isinstance(spec, dict):
        return False
    t = spec.get("type")
    if t == "which":
        return any(_which(b) for b in spec.get("bin", []))
    if t == "dir":
        return Path(os.path.expanduser(spec.get("path", ""))).is_dir()
    return False


def _validate_item(item: dict) -> bool:
    """Validasi ketat item dari remote: id unik, command list-of-str, detect valid."""
    if not isinstance(item, dict):
        return False
    if not isinstance(item.get("id"), str) or not item["id"]:
        return False
    if not isinstance(item.get("name"), str) or not isinstance(item.get("category"), str):
        return False
    for key in ("install", "uninstall"):
        cmd = item.get(key)
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            return False
    if not isinstance(item.get("detect"), dict):
        return False
    return True


def _load_catalog() -> list[dict]:
    """Katalog efektif: remote (cache) kalau ada, else statis."""
    if not APPSTORE_URL:
        return CATALOG
    cached = _read_cache()
    if cached is not None:
        return cached
    fetched = _fetch_remote()
    if fetched is not None:
        _write_cache(fetched)
        return fetched
    # remote gagal & tak ada cache → fallback statis
    return CATALOG


def _read_cache():
    try:
        if not APPSTORE_CACHE.exists():
            return None
        age = time.time() - APPSTORE_CACHE.stat().st_mtime
        if age > APPSTORE_TTL:
            return None
        data = json.loads(APPSTORE_CACHE.read_text())
        return _parse_items(data)
    except Exception:
        return None


def _write_cache(items: list[dict]) -> None:
    try:
        APPSTORE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        APPSTORE_CACHE.write_text(json.dumps({"version": 1, "items": items}))
    except Exception:
        pass


def _fetch_remote() -> list[dict] | None:
    try:
        with urllib.request.urlopen(APPSTORE_URL, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        return _parse_items(data)
    except Exception:
        return None


def _parse_items(data) -> list[dict] | None:
    """Ambil items dari JSON, validasi, tolak duplikat id."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    items, seen = [], set()
    for it in data["items"]:
        if not _validate_item(it):
            continue
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        items.append(it)
    return items or None


def list_catalog() -> list[dict]:
    """Katalog + status terinstall tiap item."""
    out = []
    for item in _load_catalog():
        try:
            installed = bool(_detect(item["detect"]))
        except Exception:
            installed = False
        out.append({
            "id": item["id"], "name": item["name"], "category": item["category"],
            "desc": item.get("desc", ""), "installed": installed,
            "service": item.get("service", ""),
        })
    return out


def install(item_id: str) -> dict:
    item = _find(item_id)
    if _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} sudah terinstall")
    res = _run(item["install"])
    if res.returncode != 0:
        raise AppStoreError(res.stderr.strip() or res.stdout.strip() or f"install {item_id} gagal")
    _log_install(item_id, "install", res)
    return {"ok": True, "id": item_id, "name": item["name"]}


def uninstall(item_id: str) -> dict:
    item = _find(item_id)
    if not _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} tidak terinstall")
    res = _run(item["uninstall"])
    if res.returncode != 0:
        raise AppStoreError(res.stderr.strip() or res.stdout.strip() or f"uninstall {item_id} gagal")
    _log_install(item_id, "uninstall", res)
    return {"ok": True, "id": item_id, "name": item["name"]}


def _find(item_id: str) -> dict:
    for item in _load_catalog():
        if item["id"] == item_id:
            return item
    raise AppStoreError(f"App tidak dikenal: {item_id}")

def service_units() -> dict[str, str]:
    """Map id item → nama unit systemd (hanya item yang punya service)."""
    return {i["id"]: i["service"] for i in _load_catalog() if i.get("service")}

def service_action(item_id: str, action: str) -> dict:
    """start/stop/restart/reload service systemd milik item."""
    if action not in SERVICE_ACTIONS:
        raise AppStoreError(f"Action tak dikenal: {action}")
    item = _find(item_id)
    unit = item.get("service")
    if not unit:
        raise AppStoreError(f"{item['name']} tidak punya service systemd")
    if not _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} tidak terinstall")
    res = _run([SYSTEMCTL, action, unit])
    if res.returncode != 0:
        raise AppStoreError(res.stderr.strip() or res.stdout.strip() or f"systemctl {action} {unit} gagal")
    return {"ok": True, "id": item_id, "name": item["name"], "action": action, "unit": unit}

def service_status(item_id: str) -> str:
    """Status systemd: active / inactive / failed / unknown. '' kalau tanpa service."""
    try:
        item = _find(item_id)
    except AppStoreError:
        return ""
    unit = item.get("service")
    if not unit:
        return ""
    res = _run([SYSTEMCTL, "is-active", unit])
    return res.stdout.strip() or "unknown"


def _log_install(item_id: str, action: str, res: subprocess.CompletedProcess | None) -> None:
    """Catat ke log file (opsional)."""
    try:
        APPSTORE_LOG.parent.mkdir(parents=True, exist_ok=True)
        rc = res.returncode if res is not None else "?"
        with APPSTORE_LOG.open("a") as f:
            f.write(f"[{action}] {item_id} rc={rc}\n")
    except Exception:
        pass