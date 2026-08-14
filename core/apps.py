"""Operasi aplikasi per-site: systemd unit (node/python/go) + docker compose.

Runtime didukung:
  node   — `node <entry>` (default index.js), PORT env
  python — `gunicorn <entry>` (default app:app), bind 127.0.0.1:<port>
  go     — binary <entry> (default ./app), PORT env
  docker — `docker compose -f <root>/docker-compose.yml up|down|restart`

Unit systemd: `ccpanel-<domain-sanitized>.service` di SYSTEMD_DIR.
Log via journalctl (systemd) — bisa dites dengan fake journalctl via PATH.
Semua path + binary bisa dioverride env utk testing.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SYSTEMD_DIR = Path(os.environ.get("CCPANEL_SYSTEMD_DIR", "/etc/systemd/system"))
DOCKER_BIN = os.environ.get("CCPANEL_DOCKER_BIN", "docker")
JOURNALCTL = os.environ.get("CCPANEL_JOURNALCTL", "journalctl")
PROJECT_ROOT = Path(os.environ.get("CCPANEL_PROJECT_ROOT", "/www/project"))

APP_TYPES = ["node", "python", "go", "docker"]
DEFAULT_ENTRY = {"node": "index.js", "python": "app:app", "go": "app", "docker": "docker-compose.yml"}
DEFAULT_USER = "www"
NODE_VERSIONS = ["v22", "v20", "v18", "v16"]
GO_VERSIONS = ["1.23", "1.22", "1.21", "1.20"]


class AppError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 30, as_www: bool = False) -> subprocess.CompletedProcess:
    if as_www:
        cmd = ["sudo", "-u", DEFAULT_USER] + cmd
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AppError(f"Perintah tidak ditemukan: {cmd[0]}")
    except subprocess.TimeoutExpired as e:
        raise AppError(f"Timeout: {' '.join(cmd)}") from e

def _run_in(cmd: list[str], cwd: Path, timeout: int = 600, as_www: bool = False) -> subprocess.CompletedProcess:
    """Jalankan perintah di folder project (install deps dll, lama)."""
    if as_www:
        cmd = ["sudo", "-u", DEFAULT_USER] + cmd
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AppError(f"Perintah tidak ditemukan: {cmd[0]}")
    except subprocess.TimeoutExpired as e:
        raise AppError(f"Timeout: {' '.join(cmd)}") from e

def _node_env_prefix(node_version: str) -> str:
    """Prefix PATH versi node via nvm (sama seperti _cmdline)."""
    if node_version:
        return f"export PATH=$HOME/.nvm/versions/node/{node_version}/bin:$PATH && "
    return ""

def _read_json(path: Path) -> dict | None:
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def resolve_entry(app_type: str, root: Path, entry: str) -> str:
    """Auto-detect entry kalau kosong/"auto":
    node   — package.json main -> scripts.start -> entry manual
    python — app.py -> main.py -> wsgi.py
    go     — entry manual (binary hasil build)
    """
    e = (entry or "").strip()
    if e and e != "auto":
        return e
    if app_type == "node":
        pkg = _read_json(root / "package.json")
        if pkg:
            if pkg.get("main"):
                return str(pkg["main"])
            start = (pkg.get("scripts") or {}).get("start")
            if start:
                return re.sub(r"^node\s+", "", start.strip()).strip() or "index.js"
        return "index.js"
    if app_type == "python":
        for cand, entry_val in (("app.py", "app:app"), ("main.py", "main:app"), ("wsgi.py", "wsgi:application")):
            if (root / cand).exists():
                return entry_val
        return "app:app"
    return entry or "app"

def _install_deps(app_type: str, root: Path, run_user: str, node_version: str = "") -> None:
    """Install dependensi otomatis sebelum start:
    node   — npm install (npm ci kalau ada package-lock.json)
    python — pip install -r requirements.txt
    go     — go build -o <name> (pakai nama folder sebagai binary)
    Skip kalau folder kosong, sudah terinstall, atau perintah tak ada.
    """
    if not any(root.iterdir()):
        return
    if app_type == "node":
        if not (root / "package.json").exists():
            return
        if (root / "node_modules").exists():
            return
        pkg = _read_json(root / "package.json")
        if not pkg or not (pkg.get("dependencies") or pkg.get("devDependencies")):
            return
        env = _node_env_prefix(node_version)
        lock = root / "package-lock.json"
        npm = "npm ci" if lock.exists() else "npm install"
        res = _run_in(["bash", "-lc", f"cd {root} && {env} {npm}"], root, timeout=900, as_www=True)
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or f"{npm} gagal")
    elif app_type == "python":
        req = root / "requirements.txt"
        if not req.exists():
            return
        # cek venv project dulu, fallback pip
        venv_pip = root / ".venv" / "bin" / "pip"
        cmd = [str(venv_pip), "install", "-r", str(req)] if venv_pip.exists() else ["pip", "install", "-r", str(req)]
        res = _run_in(cmd, root, timeout=900, as_www=True)
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "pip install -r requirements.txt gagal")
    elif app_type == "go":
        if not (root / "go.mod").exists():
            return
        if (root / "go.sum").exists():
            res = _run_in(["go", "mod", "download"], root, timeout=900, as_www=True)
            if res.returncode != 0:
                raise AppError(res.stderr.strip() or "go mod download gagal")
        bin_name = root.name
        res = _run_in(["go", "build", "-o", bin_name, "."], root, timeout=900, as_www=True)
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "go build gagal")

def _prepare_project(app_type: str, root: Path, run_user: str, node_version: str = "") -> None:
    """Siapkan folder project: buat kalau belum ada + install deps."""
    root.mkdir(parents=True, exist_ok=True)
    _install_deps(app_type, root, run_user, node_version)


def unit_name(domain: str) -> str:
    """ccpanel-example-com.service — domain sanitized (dots → dash)."""
    safe = re.sub(r"[^a-zA-Z0-9]", "-", domain)
    return f"ccpanel-{safe}.service"

def project_root(name: str) -> Path:
    """Folder project standalone: PROJECT_ROOT/<nama>."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
        raise AppError("Nama project hanya huruf/angka/-/_ (max 64)")
    return PROJECT_ROOT / name

def standalone_unit_name(name: str) -> str:
    """ccpanel-proj-<name>.service — unit project standalone (tanpa domain)."""
    safe = re.sub(r"[^a-zA-Z0-9]", "-", name)
    return f"ccpanel-proj-{safe}.service"

def _standalone_unit_path(name: str) -> Path:
    return SYSTEMD_DIR / standalone_unit_name(name)

def node_versions() -> list[str]:
    """Deteksi versi node terinstall: nvm dir dulu, fallback NODE_VERSIONS."""
    nvm = Path(os.path.expanduser("~/.nvm/versions/node"))
    if nvm.is_dir():
        return sorted(
            (d.name for d in nvm.iterdir() if d.is_dir() and re.match(r"^v\d+", d.name)),
            reverse=True,
        ) or NODE_VERSIONS
    return NODE_VERSIONS


def go_versions() -> list[str]:
    """Deteksi versi Go terinstall: sdk dir dulu, fallback GO_VERSIONS."""
    # Common Go install paths
    paths = [
        Path("/usr/local/go"),
        Path("/opt/go"),
        Path(os.path.expanduser("~/go")),
        Path(os.path.expanduser("~/.go")),
    ]
    for p in paths:
        if p.is_dir():
            # Check for version in directory name or version file
            version_file = p / "VERSION"
            if version_file.exists():
                try:
                    v = version_file.read_text().strip().split('\n')[0]  # first line only
                    if v.startswith("go"):
                        return [v[2:]]  # strip "go" prefix
                except Exception:
                    pass
    # Fallback: try `go version` command
    try:
        res = subprocess.run(["go", "version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            # go version go1.23.0 linux/amd64
            m = re.search(r"go(\d+\.\d+(?:\.\d+)?)", res.stdout)
            if m:
                return [m.group(1)]
    except Exception:
        pass
    return GO_VERSIONS


def _unit_path(domain: str) -> Path:
    return SYSTEMD_DIR / unit_name(domain)


def _compose_file(root: Path) -> Path:
    return root / "docker-compose.yml"


# ------------------------------------------------------------- unit content

def _cmdline(app_type: str, root: Path, entry: str, port: int, run_opt: str = "",
             pm2: bool = False, name: str = "", node_version: str = "", go_version: str = "") -> str:
    if app_type == "node":
        # PM2: pm2 start <entry> --name <name> -- <run_opt>; env NODE_PATH versi node
        if pm2:
            script = (root / entry).resolve() if Path(entry).is_absolute() else entry
            cmd = f"pm2 start {script} --name {name or 'app'}"
            if run_opt:
                cmd += f" -- {run_opt}"
            return cmd
        env = _node_env_prefix(node_version)
        # kalau package.json punya scripts.start -> npm start (deps terinstall otomatis)
        pkg = _read_json(root / "package.json")
        if pkg and (pkg.get("scripts") or {}).get("start"):
            cmd = "/usr/bin/env npm start"
            if run_opt:
                cmd += f" -- {run_opt}"
            return env + cmd
        cmd = f"/usr/bin/env node {entry}"
        if run_opt:
            cmd += f" {run_opt}"
        return env + cmd
    if app_type == "python":
        return f"/usr/bin/env gunicorn {entry} --bind 127.0.0.1:{port}"
    if app_type == "go":
        # go versi via GOROOT/GOPATH atau PATH
        env = ""
        if go_version:
            # Try common Go install paths
            env = f"export PATH=/usr/local/go/bin:/opt/go/bin:$HOME/go/bin:$PATH && "
        # binary hasil build otomatis (nama = folder), atau entry manual user
        bin_name = entry if (root / entry).exists() and entry != root.name else root.name
        cmd = f"/usr/bin/env ./{bin_name}"
        if run_opt:
            cmd += f" {run_opt}"
        return env + cmd
    raise AppError(f"app_type tidak valid: {app_type}")


UNIT_TEMPLATE = """[Unit]
Description=CCPanel app {domain} ({app_type})
After=network.target

[Service]
Type=simple
User={user}
WorkingDirectory={root}
Environment=PORT={port}
ExecStart={cmd}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def _write_unit(domain: str, root: Path, app_type: str, port: int, entry: str,
                user: str = DEFAULT_USER, run_opt: str = "", pm2: bool = False,
                name: str = "", node_version: str = "", go_version: str = "") -> None:
    _write_unit_to(_unit_path(domain), domain, root, app_type, port, entry,
                   user, run_opt, pm2, name, node_version, go_version)

def _write_unit_to(path: Path, label: str, root: Path, app_type: str, port: int,
                   entry: str, user: str, run_opt: str, pm2: bool, name: str,
                   node_version: str, go_version: str = "") -> None:
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    cmd = _cmdline(app_type, root, entry, port, run_opt, pm2, name, node_version, go_version)
    path.write_text(
        UNIT_TEMPLATE.format(domain=label, app_type=app_type, root=root, port=port,
                             cmd=cmd, user=user)
    )


# ----------------------------------------------------------------- control

def systemctl(*args: str) -> subprocess.CompletedProcess:
    return _run([os.environ.get("CCPANEL_SYSTEMCTL", "systemctl"), *args])


def create_app(domain: str, root: Path, app_type: str, port: int, entry: str,
               user: str = DEFAULT_USER, run_opt: str = "", pm2: bool = False,
               name: str = "", node_version: str = "", go_version: str = "") -> None:
    """Tulis unit (systemd) atau siapkan compose (docker), lalu start."""
    if app_type not in APP_TYPES:
        raise AppError(f"app_type tidak valid. Pilihan: {', '.join(APP_TYPES)}")
    if not 1 <= port <= 65535:
        raise AppError(f"Port tidak valid: {port}")
    if app_type == "docker":
        if not _compose_file(root).exists():
            raise AppError(f"docker-compose.yml tidak ada di {root}")
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "up", "-d"])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "docker compose up gagal")
        return
    # node/python/go: siapkan deps dulu, lalu tulis unit systemd
    _prepare_project(app_type, root, user, node_version)
    if app_type == "go" and not (root / entry).exists() and not (root / root.name).exists():
        raise AppError(f"Binary {entry} tidak ada di {root} (atau go.mod untuk build otomatis)")
    _do_create(_unit_path(domain), domain, root, app_type, port, entry,
               user, run_opt, pm2, name, node_version, go_version)

def create_standalone(name: str, app_type: str, port: int, entry: str,
                      user: str = DEFAULT_USER, run_opt: str = "", pm2: bool = False,
                      node_version: str = "", go_version: str = "") -> Path:
    """Pasang project standalone (tanpa domain): unit ccpanel-proj-<name>.
    Folder PROJECT_ROOT/<name> dibuat kalau belum ada. Return root path."""
    root = project_root(name)
    if app_type not in APP_TYPES:
        raise AppError(f"app_type tidak valid. Pilihan: {', '.join(APP_TYPES)}")
    if not 1 <= port <= 65535:
        raise AppError(f"Port tidak valid: {port}")
    if app_type == "docker":
        if not _compose_file(root).exists():
            raise AppError(f"docker-compose.yml tidak ada di {root}")
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "up", "-d"])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "docker compose up gagal")
        return root
    # siapkan folder + install deps sebelum unit di-start
    _prepare_project(app_type, root, user, node_version)
    if app_type == "go" and not (root / entry).exists() and not (root / root.name).exists():
        raise AppError(f"Binary {entry} tidak ada di {root} (atau go.mod untuk build otomatis)")
    _do_create(_standalone_unit_path(name), name, root, app_type, port, entry,
               user, run_opt, pm2, name, node_version, go_version)
    return root

def _do_create(path: Path, label: str, root: Path, app_type: str, port: int,
               entry: str, user: str, run_opt: str, pm2: bool, name: str,
               node_version: str, go_version: str = "") -> None:
    _write_unit_to(path, label, root, app_type, port, entry, user, run_opt, pm2,
                   name, node_version, go_version)
    res = systemctl("daemon-reload")
    if res.returncode != 0:
        raise AppError(res.stderr.strip() or "systemctl daemon-reload gagal")
    res = systemctl("enable", "--now", path.name)
    if res.returncode != 0:
        raise AppError(res.stderr.strip() or f"systemctl enable {path.name} gagal")


def app_action(domain: str, root: Path, app_type: str, action: str) -> None:
    """start/stop/restart/status. Docker pakai compose, sisanya systemd."""
    valid = {"start", "stop", "restart", "status"}
    if action not in valid:
        raise AppError(f"Aksi tidak valid: {action}")
    if app_type == "docker":
        cmd = {
            "start": ["up", "-d"],
            "stop": ["stop"],
            "restart": ["restart"],
            "status": ["ps"],
        }[action]
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), *cmd])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or f"docker compose {action} gagal")
        return
    res = systemctl(action, unit_name(domain))
    if res.returncode != 0:
        raise AppError(res.stderr.strip() or f"systemctl {action} {unit_name(domain)} gagal")

def standalone_action(name: str, app_type: str, action: str) -> None:
    """start/stop/restart/status untuk project standalone."""
    valid = {"start", "stop", "restart", "status"}
    if action not in valid:
        raise AppError(f"Aksi tidak valid: {action}")
    if app_type == "docker":
        root = project_root(name)
        cmd = {
            "start": ["up", "-d"],
            "stop": ["stop"],
            "restart": ["restart"],
            "status": ["ps"],
        }[action]
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), *cmd])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or f"docker compose {action} gagal")
        return
    unit = standalone_unit_name(name)
    res = systemctl(action, unit)
    if res.returncode != 0:
        raise AppError(res.stderr.strip() or f"systemctl {action} {unit} gagal")

def standalone_status(name: str, app_type: str) -> dict:
    """Status project standalone + PID (systemd MainPID)."""
    if app_type == "docker":
        root = project_root(name)
        try:
            res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "ps", "--format", "{{.Status}}"])
        except AppError as e:
            # docker tak terinstall → service tak mungkin jalan
            return {"state": "inactive", "detail": str(e)}
        if res.returncode != 0:
            return {"state": "inactive", "detail": res.stderr.strip()}
        out = res.stdout.strip()
        if "Up" in out:
            return {"state": "running", "detail": out}
        if out:
            return {"state": "stopped", "detail": out}
        return {"state": "inactive", "detail": ""}
    unit = standalone_unit_name(name)
    res = systemctl("is-active", unit)
    state = res.stdout.strip() or "inactive"
    detail = res.stderr.strip()
    pid = project_pid(name)
    return {"state": state, "detail": detail, "pid": pid}

def project_pid(name: str) -> int | None:
    """MainPID dari systemd show. 0/tidak ada → None."""
    res = _run(["systemctl", "show", standalone_unit_name(name), "-p", "MainPID", "--value"])
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    if not out.isdigit() or int(out) == 0:
        return None
    return int(out)


def app_status(domain: str, root: Path, app_type: str) -> dict:
    """Status aktif. systemd: `is-active`. docker: `compose ps` (parsing
    container status line). Kalau unit tidak ada → "inactive"."""
    if app_type == "docker":
        try:
            res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "ps", "--format", "{{.Status}}"])
        except AppError as e:
            return {"state": "inactive", "detail": str(e)}
        if res.returncode != 0:
            return {"state": "inactive", "detail": res.stderr.strip()}
        out = res.stdout.strip()
        if "Up" in out:
            return {"state": "running", "detail": out}
        if out:
            return {"state": "stopped", "detail": out}
        return {"state": "inactive", "detail": ""}
    res = systemctl("is-active", unit_name(domain))
    state = res.stdout.strip() or "inactive"
    return {"state": state, "detail": res.stderr.strip()}


def remove_app(domain: str, root: Path, app_type: str) -> None:
    """Stop + hapus unit/compose. Tidak hapus file project."""
    if app_type == "docker":
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "down"])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "docker compose down gagal")
        return
    systemctl("stop", unit_name(domain))
    systemctl("disable", unit_name(domain))
    _unit_path(domain).unlink(missing_ok=True)
    systemctl("daemon-reload")

def remove_standalone(name: str, app_type: str) -> None:
    """Stop + hapus unit/compose project standalone. Tidak hapus folder project."""
    if app_type == "docker":
        root = project_root(name)
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "down"])
        if res.returncode != 0:
            raise AppError(res.stderr.strip() or "docker compose down gagal")
        return
    unit = standalone_unit_name(name)
    systemctl("stop", unit)
    systemctl("disable", unit)
    _standalone_unit_path(name).unlink(missing_ok=True)
    systemctl("daemon-reload")


def log_tail(domain: str, root: Path, app_type: str, lines: int = 100) -> str:
    """Tail log. systemd: journalctl -u unit -n. docker: compose logs --tail."""
    if app_type == "docker":
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "logs", "--tail", str(lines)])
        return res.stdout + res.stderr
    res = _run([JOURNALCTL, "-u", unit_name(domain), "-n", str(lines), "--no-pager"])
    return res.stdout + res.stderr

def standalone_log_tail(name: str, app_type: str, lines: int = 100) -> str:
    """Tail log project standalone (unit ccpanel-proj-<name>)."""
    if app_type == "docker":
        root = project_root(name)
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "logs", "--tail", str(lines)])
        return res.stdout + res.stderr
    res = _run([JOURNALCTL, "-u", standalone_unit_name(name), "-n", str(lines), "--no-pager"])
    return res.stdout + res.stderr
