"""App Store: katalog runtime + aplikasi pendukung server, deteksi status,
install/uninstall. Semua perintah via subprocess argumen-list (tanpa shell).

Katalog bisa dinamis: fetch JSON dari URL remote (misal raw GitHub), cache
lokal dengan TTL, fallback ke katalog statis bawaan kalau offline/gagal.

Kategori:
  php    — versi PHP-FPM (7.4, 8.0, 8.1, 8.2, 8.3)
  node   — Node.js via nvm (v18, v20, v22, v24)
  go     — Go SDK (1.22, 1.23, 1.24)
  app    — aplikasi pendukung (nginx, mysql, redis, git, composer, pm2, docker)

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

# id unik + command list-of-str + detect data-driven (bukan lambda) supaya
# bisa diserialisasi ke JSON remote.
CATALOG: list[dict] = [
    # ---- PHP ----
    {"id": "php7.4", "name": "PHP 7.4", "category": "php", "desc": "PHP-FPM 7.4 (legacy)",
     "install": [APT, "install", "-y", "php7.4-fpm"], "uninstall": [APT, "remove", "-y", "php7.4-fpm"],
     "detect": {"type": "which", "bin": ["php7.4", "php-fpm7.4"]}},
    {"id": "php8.0", "name": "PHP 8.0", "category": "php", "desc": "PHP-FPM 8.0",
     "install": [APT, "install", "-y", "php8.0-fpm"], "uninstall": [APT, "remove", "-y", "php8.0-fpm"],
     "detect": {"type": "which", "bin": ["php8.0", "php-fpm8.0"]}},
    {"id": "php8.1", "name": "PHP 8.1", "category": "php", "desc": "PHP-FPM 8.1",
     "install": [APT, "install", "-y", "php8.1-fpm"], "uninstall": [APT, "remove", "-y", "php8.1-fpm"],
     "detect": {"type": "which", "bin": ["php8.1", "php-fpm8.1"]}},
    {"id": "php8.2", "name": "PHP 8.2", "category": "php", "desc": "PHP-FPM 8.2",
     "install": [APT, "install", "-y", "php8.2-fpm"], "uninstall": [APT, "remove", "-y", "php8.2-fpm"],
     "detect": {"type": "which", "bin": ["php8.2", "php-fpm8.2"]}},
    {"id": "php8.3", "name": "PHP 8.3", "category": "php", "desc": "PHP-FPM 8.3",
     "install": [APT, "install", "-y", "php8.3-fpm"], "uninstall": [APT, "remove", "-y", "php8.3-fpm"],
     "detect": {"type": "which", "bin": ["php8.3", "php-fpm8.3"]}},
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
     "detect": {"type": "which", "bin": ["nginx"]}},
    {"id": "mariadb", "name": "MariaDB", "category": "app", "desc": "Database server",
     "install": [APT, "install", "-y", "mariadb-server"], "uninstall": [APT, "remove", "-y", "mariadb-server"],
     "detect": {"type": "which", "bin": ["mysql", "mariadb"]}},
    {"id": "redis", "name": "Redis", "category": "app", "desc": "In-memory key-value store",
     "install": [APT, "install", "-y", "redis-server"], "uninstall": [APT, "remove", "-y", "redis-server"],
     "detect": {"type": "which", "bin": ["redis-server"]}},
    {"id": "postgresql", "name": "PostgreSQL", "category": "app", "desc": "Relational database",
     "install": [APT, "install", "-y", "postgresql"], "uninstall": [APT, "remove", "-y", "postgresql"],
     "detect": {"type": "which", "bin": ["psql"]}},
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


def _log_install(item_id: str, action: str, res: subprocess.CompletedProcess) -> None:
    """Catat ke log file (opsional)."""
    try:
        APPSTORE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with APPSTORE_LOG.open("a") as f:
            f.write(f"[{action}] {item_id} rc={res.returncode}\n")
    except Exception:
        pass