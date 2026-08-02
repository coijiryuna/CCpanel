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


class AppError(Exception):
    pass


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AppError(f"Timeout: {' '.join(cmd)}") from e


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


def _unit_path(domain: str) -> Path:
    return SYSTEMD_DIR / unit_name(domain)


def _compose_file(root: Path) -> Path:
    return root / "docker-compose.yml"


# ------------------------------------------------------------- unit content

def _cmdline(app_type: str, root: Path, entry: str, port: int, run_opt: str = "",
             pm2: bool = False, name: str = "", node_version: str = "") -> str:
    if app_type == "node":
        # PM2: pm2 start <entry> --name <name> -- <run_opt>; env NODE_PATH versi node
        if pm2:
            script = (root / entry).resolve() if Path(entry).is_absolute() else entry
            cmd = f"pm2 start {script} --name {name or 'app'}"
            if run_opt:
                cmd += f" -- {run_opt}"
            return cmd
        # node versi via nvm PATH (kalau ada), default node
        env = ""
        if node_version:
            env = f"export PATH=$HOME/.nvm/versions/node/{node_version}/bin:$PATH && "
        cmd = f"/usr/bin/env node {entry}"
        if run_opt:
            cmd += f" {run_opt}"
        return env + cmd
    if app_type == "python":
        return f"/usr/bin/env gunicorn {entry} --bind 127.0.0.1:{port}"
    if app_type == "go":
        return str((root / entry).resolve())
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
                name: str = "", node_version: str = "") -> None:
    _write_unit_to(_unit_path(domain), domain, root, app_type, port, entry,
                   user, run_opt, pm2, name, node_version)

def _write_unit_to(path: Path, label: str, root: Path, app_type: str, port: int,
                   entry: str, user: str, run_opt: str, pm2: bool, name: str,
                   node_version: str) -> None:
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    cmd = _cmdline(app_type, root, entry, port, run_opt, pm2, name, node_version)
    path.write_text(
        UNIT_TEMPLATE.format(domain=label, app_type=app_type, root=root, port=port,
                             cmd=cmd, user=user)
    )


# ----------------------------------------------------------------- control

def systemctl(*args: str) -> subprocess.CompletedProcess:
    return _run(["systemctl", *args])


def create_app(domain: str, root: Path, app_type: str, port: int, entry: str,
               user: str = DEFAULT_USER, run_opt: str = "", pm2: bool = False,
               name: str = "", node_version: str = "") -> None:
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
    # node/python/go: tulis unit systemd
    if app_type == "go":
        bin_path = root / entry
        if not bin_path.exists():
            raise AppError(f"Binary {entry} tidak ada di {root}")
        bin_path.chmod(0o755)
    _do_create(_unit_path(domain), domain, root, app_type, port, entry,
               user, run_opt, pm2, name, node_version)

def create_standalone(name: str, app_type: str, port: int, entry: str,
                      user: str = DEFAULT_USER, run_opt: str = "", pm2: bool = False,
                      node_version: str = "") -> Path:
    """Pasang project standalone (tanpa domain): unit ccpanel-proj-<name>.
    Folder PROJECT_ROOT/<name> dibuat kalau belum ada. Return root path."""
    root = project_root(name)
    root.mkdir(parents=True, exist_ok=True)
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
    if app_type == "go":
        bin_path = root / entry
        if not bin_path.exists():
            raise AppError(f"Binary {entry} tidak ada di {root}")
        bin_path.chmod(0o755)
    _do_create(_standalone_unit_path(name), name, root, app_type, port, entry,
               user, run_opt, pm2, name, node_version)
    return root

def _do_create(path: Path, label: str, root: Path, app_type: str, port: int,
               entry: str, user: str, run_opt: str, pm2: bool, name: str,
               node_version: str) -> None:
    _write_unit_to(path, label, root, app_type, port, entry, user, run_opt, pm2,
                   name, node_version)
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
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "ps", "--format", "{{.Status}}"])
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
        res = _run([DOCKER_BIN, "compose", "-f", str(_compose_file(root)), "ps", "--format", "{{.Status}}"])
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
