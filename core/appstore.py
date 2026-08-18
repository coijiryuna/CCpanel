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
import time
import urllib.request
from pathlib import Path

from . import tasks as tasks_ops

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
PHP_REPO_SETUP = os.environ.get("CCPANEL_PHP_REPO_SETUP", "auto")
REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_FILE = Path(os.environ.get("CCPANEL_APPSTORE_CATALOG", REPO_ROOT / "catalog.json"))
GO_VERSION_MAP = {
    "go1.22": "1.22.12",
    "go1.23": "1.23.6",
    "go1.24": "1.24.5",
}

# Direktori binary non-PATH umum (nginx, apache2, php-fpm sering di sini).
# Bisa di-override env utk testing.
SBIN_DIRS = [
    Path(d) for d in os.environ.get(
        "CCPANEL_SBIN_DIRS", "/usr/sbin:/sbin:/usr/local/sbin:/usr/local/bin:/usr/local/lsws/bin"
    ).split(":") if d
]

# ------------------------------------------------------------------ task async
# Task install/uninstall jalan di background thread (core/tasks). Frontend
# polling status + output per baris. Status: running / done / error.

def _stream_worker(item: dict, action: str, key: str) -> None:
    """Worker thread: jalankan install/uninstall item, stream ke task."""
    try:
        cmd = item[action]
    except KeyError:
        tasks_ops.finish(key, False, f"{action} tidak ada untuk {item.get('id', '?')}")
        return
    tasks_ops.run_stream(cmd, key)
    if action == "install" and tasks_ops.status(key)["status"] == "done":
        _log_install(item.get("id", "?"), "install", None)

def start_task(item_id: str, action: str) -> dict:
    """Mulai install/uninstall async. Return task key."""
    item = _find(item_id)
    if action == "install" and _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} sudah terinstall")
    if action == "uninstall" and not _detect(item["detect"]):
        raise AppStoreError(f"{item['name']} tidak terinstall")
    key = f"{item_id}:{action}:{int(time.time())}"
    tasks_ops.start(key, lambda: _stream_worker(item, action, key))
    return {"ok": True, "id": item_id, "action": action, "key": key}

def task_status(key: str) -> dict:
    """Status task + output. Frontend polling."""
    return tasks_ops.status(key)

def task_list() -> list[dict]:
    """Semua task (belum selesai saja)."""
    return tasks_ops.list_active()

# id unik + command list-of-str + detect data-driven (bukan lambda) supaya
# bisa diserialisasi ke JSON remote.
CATALOG: list[dict] = [
    # ---- PHP ----
    {"id": "php7.4", "name": "PHP 7.4", "category": "php", "kind": "php", "desc": "PHP-FPM 7.4 (legacy)",
     "install": [APT, "install", "-y", "php7.4-fpm"], "uninstall": [APT, "remove", "-y", "php7.4-fpm"],
     "detect": {"type": "which", "bin": ["php7.4", "php-fpm7.4"]}, "service": "php7.4-fpm"},
    {"id": "php8.0", "name": "PHP 8.0", "category": "php", "kind": "php", "desc": "PHP-FPM 8.0",
     "install": [APT, "install", "-y", "php8.0-fpm"], "uninstall": [APT, "remove", "-y", "php8.0-fpm"],
     "detect": {"type": "which", "bin": ["php8.0", "php-fpm8.0"]}, "service": "php8.0-fpm"},
    {"id": "php8.1", "name": "PHP 8.1", "category": "php", "kind": "php", "desc": "PHP-FPM 8.1",
     "install": [APT, "install", "-y", "php8.1-fpm"], "uninstall": [APT, "remove", "-y", "php8.1-fpm"],
     "detect": {"type": "which", "bin": ["php8.1", "php-fpm8.1"]}, "service": "php8.1-fpm"},
    {"id": "php8.2", "name": "PHP 8.2", "category": "php", "kind": "php", "desc": "PHP-FPM 8.2",
     "install": [APT, "install", "-y", "php8.2-fpm"], "uninstall": [APT, "remove", "-y", "php8.2-fpm"],
     "detect": {"type": "which", "bin": ["php8.2", "php-fpm8.2"]}, "service": "php8.2-fpm"},
    {"id": "php8.3", "name": "PHP 8.3", "category": "php", "kind": "php", "desc": "PHP-FPM 8.3",
     "install": [APT, "install", "-y", "php8.3-fpm"], "uninstall": [APT, "remove", "-y", "php8.3-fpm"],
     "detect": {"type": "which", "bin": ["php8.3", "php-fpm8.3"]}, "service": "php8.3-fpm"},
    {"id": "php8.4", "name": "PHP 8.4", "category": "php", "kind": "php", "desc": "PHP-FPM 8.4 (Debian 13/trixie)",
     "install": [APT, "install", "-y", "php8.4-fpm"], "uninstall": [APT, "remove", "-y", "php8.4-fpm"],
     "detect": {"type": "which", "bin": ["php8.4", "php-fpm8.4"]}, "service": "php8.4-fpm"},
    # ---- Node (nvm) ----
    {"id": "node18", "name": "Node.js 18", "category": "node", "kind": "node", "desc": "Node.js v18 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 18"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 18"],
     "detect": {"type": "any", "items": [{"type": "which", "bin": ["node"]}, {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v18")}]}},
    {"id": "node20", "name": "Node.js 20", "category": "node", "kind": "node", "desc": "Node.js v20 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 20"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 20"],
     "detect": {"type": "any", "items": [{"type": "which", "bin": ["node"]}, {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v20")}]}},
    {"id": "node22", "name": "Node.js 22", "category": "node", "kind": "node", "desc": "Node.js v22 LTS via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 22"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 22"],
     "detect": {"type": "any", "items": [{"type": "which", "bin": ["node"]}, {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v22")}]}},
    {"id": "node24", "name": "Node.js 24", "category": "node", "kind": "node", "desc": "Node.js v24 via nvm",
     "install": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm install 24"],
     "uninstall": ["bash", "-lc", f"source {NVM_DIR}/nvm.sh && nvm uninstall 24"],
     "detect": {"type": "any", "items": [{"type": "which", "bin": ["node"]}, {"type": "dir", "path": str(NVM_DIR / "versions" / "node" / "v24")}]}},
    # ---- Go SDK ----
    {"id": "go1.22", "name": "Go 1.22", "category": "go", "kind": "go", "desc": "Go SDK 1.22",
     "install": ["bash", "-lc", f"mkdir -p {GO_ROOT} && curl -sSL https://go.dev/dl/go1.22.linux-amd64.tar.gz | tar -C {GO_ROOT} -xzf - && mv {GO_ROOT}/go {GO_ROOT}/go1.22"],
     "uninstall": ["rm", "-rf", str(GO_ROOT / "go1.22")],
     "detect": {"type": "dir", "path": str(GO_ROOT / "go1.22")}},
    {"id": "go1.23", "name": "Go 1.23", "category": "go", "kind": "go", "desc": "Go SDK 1.23",
     "install": ["bash", "-lc", f"mkdir -p {GO_ROOT} && wget -qO- https://go.dev/dl/go1.23.linux-amd64.tar.gz | tar -C {GO_ROOT} -xzf && mv {GO_ROOT}/go {GO_ROOT}/go1.23"],
     "uninstall": ["rm", "-rf", str(GO_ROOT / "go1.23")],
     "detect": {"type": "dir", "path": str(GO_ROOT / "go1.23")}},
    {"id": "go1.24", "name": "Go 1.24", "category": "go", "kind": "go", "desc": "Go SDK 1.24",
     "install": ["bash", "-lc", f"mkdir -p {GO_ROOT} && wget -qO- https://go.dev/dl/go1.24.linux-amd64.tar.gz | tar -C {GO_ROOT} -xz && mv {GO_ROOT}/go {GO_ROOT}/go1.24"],
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


def _php_install_cmd(version: str) -> list[str]:
    return ["bash", "-lc", (
        "set -e; "
        "export DEBIAN_FRONTEND=noninteractive; "
        "if ! command -v php{v}-fpm >/dev/null 2>&1; then "
        "  if [ \"$CCPANEL_PHP_REPO_SETUP\" = auto ] || [ \"$CCPANEL_PHP_REPO_SETUP\" = yes ]; then "
        "    if ! apt-cache show php{v}-fpm >/dev/null 2>&1; then "
        "      if [ ! -f /etc/apt/sources.list.d/ondrej-php.list ] && [ ! -f /etc/apt/sources.list.d/php.list ]; then "
        "        apt-get update; "
        "        apt-get install -y software-properties-common ca-certificates curl gnupg; "
        "        if command -v add-apt-repository >/dev/null 2>&1; then "
        "          add-apt-repository -y ppa:ondrej/php; "
        "        fi; "
        "        if [ -n \"$(command -v wget 2>/dev/null)\" ] || command -v curl >/dev/null 2>&1; then true; fi; "
        "        apt-get update; "
        "      fi; "
        "    fi; "
        "  fi; "
        "  apt-get update; apt-get install -y php{v}-fpm php{v}-cli php{v}-common; "
        "fi"
    ).format(v=version)]


def _node_install_cmd(version: str) -> list[str]:
    return ["bash", "-lc", (
        "set -e; "
        "export NVM_DIR=\"${{NVM_DIR:-$HOME/.nvm}}\"; "
        "mkdir -p \"$NVM_DIR\"; "
        "if [ ! -s \"$NVM_DIR/nvm.sh\" ]; then "
        "  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash; "
        "fi; "
        ". \"$NVM_DIR/nvm.sh\"; "
        "nvm install {v}; nvm alias default {v}"
    ).format(v=version)]


def _go_install_cmd(version: str) -> list[str]:
    gover = GO_VERSION_MAP[version]
    return ["bash", "-lc", (
        "set -e; "
        "tmp=$(mktemp -d); "
        "arch=$(dpkg --print-architecture); "
        "case \"$arch\" in amd64) goarch=amd64 ;; arm64) goarch=arm64 ;; *) echo 'unsupported arch'; exit 1 ;; esac; "
        "curl -fsSL -o \"$tmp/go.tgz\" https://go.dev/dl/go{ver}.linux-${{goarch}}.tar.gz; "
        "rm -rf {root}/{name}; mkdir -p {root}; "
        "tar -C {root} -xzf \"$tmp/go.tgz\"; "
        "mv {root}/go {root}/{name}; "
        "rm -rf \"$tmp\""
    ).format(ver=gover, root=str(GO_ROOT), name=version)]


def _which(bin_name: str) -> bool:
    """Cek binary ada: PATH + direktori sbin umum.

    shutil.which hanya cek PATH. Banyak binary server (nginx, apache2,
    php-fpm8.x) berada di /usr/sbin yang tidak selalu di PATH saat panel
    jalan (via systemd/dev shell). Tanpa fallback ini, aplikasi yang sudah
    terinstall tampil sebagai belum terinstall di App Store.
    """
    if shutil.which(bin_name):
        return True
    for d in SBIN_DIRS:
        if (d / bin_name).is_file():
            return True
    return False


def _detect(spec) -> bool:
    """Evaluasi spec detect data-driven. Unknown type → False (aman)."""
    if not isinstance(spec, dict):
        return False
    t = spec.get("type")
    if t == "which":
        return any(_which(b) for b in spec.get("bin", []))
    if t == "dir":
        return Path(os.path.expanduser(spec.get("path", ""))).is_dir()
    if t == "any":
        return any(_detect(item) for item in spec.get("items", []))
    if t == "all":
        return all(_detect(item) for item in spec.get("items", []))
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


def _materialize_item(item: dict) -> dict:
    out = dict(item)
    if out.get("kind") == "php":
        v = out["id"].replace("php", "")
        out["install"] = _php_install_cmd(v)
        out["uninstall"] = [APT, "remove", "-y", f"php{v}-fpm", f"php{v}-cli", f"php{v}-common"]
    elif out.get("kind") == "node":
        out["install"] = _node_install_cmd(out["id"].replace("node", ""))
        out["uninstall"] = ["bash", "-lc", f"source ${{NVM_DIR:-$HOME/.nvm}}/nvm.sh && nvm uninstall {out['id'].replace('node', '')}"]
    elif out.get("kind") == "go":
        out["install"] = _go_install_cmd(out["id"])
        out["uninstall"] = ["rm", "-rf", str(GO_ROOT / out["id"])]
    return out


def _load_catalog() -> list[dict]:
    """Katalog efektif: local catalog.json + remote/cache versioned."""
    local_version, local = _read_catalog_source(CATALOG_FILE)
    cached_version, cached = _read_catalog_source(APPSTORE_CACHE, cached=True)
    if cached is not None:
        if local is not None and cached_version >= local_version:
            return cached
        if local is None:
            return cached
    remote = _fetch_remote()
    if remote is not None:
        remote_version = _fetch_remote_version()
        if local is not None and remote_version < local_version:
            _write_cache(local_version, local)
            return local
        _write_cache(remote_version, remote)
        return remote
    if local is not None:
        _write_cache(local_version, local)
        return local
    return [_materialize_item(item) for item in CATALOG]


def _read_catalog_source(path: Path, cached: bool = False) -> tuple[int, list[dict] | None]:
    try:
        if not path.exists():
            return 0, None
        if cached:
            age = time.time() - path.stat().st_mtime
            if age > APPSTORE_TTL:
                return 0, None
        raw = json.loads(path.read_text())
        version = int(raw.get("version", 0)) if isinstance(raw, dict) else 0
        return version, _parse_items(raw)
    except Exception:
        return 0, None


def _fetch_remote_version() -> int:
    try:
        with urllib.request.urlopen(APPSTORE_URL, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        if isinstance(data, dict):
            return int(data.get("version", 0))
    except Exception:
        pass
    return 0


def _write_cache(version: int, items: list[dict]) -> None:
    try:
        APPSTORE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        APPSTORE_CACHE.write_text(json.dumps({"version": version, "items": items}))
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


def refresh_catalog(force: bool = False) -> list[dict]:
    """Manual refresh cache. force=True abaikan TTL."""
    if force and APPSTORE_CACHE.exists():
        try:
            APPSTORE_CACHE.unlink()
        except Exception:
            pass
    items = _load_catalog()
    return items


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
    # Web server: single mode — satu port 80 hanya satu engine. Start
    # nginx/apache/lsws harus stop engine lain dulu, kalau tidak bind port gagal.
    # Multi mode (nginx front 80 + backend 8288/8188): engine bisa jalan
    # barengan, JANGAN stop yang lain.
    from . import webserver as webserver_ops
    if action == "start" and unit in ("nginx", "apache2", "lsws") and not webserver_ops.is_multi():
        for other in ("nginx", "apache2", "lsws"):
            if other == unit:
                continue
            if _run([SYSTEMCTL, "is-active", "--quiet", other]).returncode == 0:
                _run([SYSTEMCTL, "stop", other])
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