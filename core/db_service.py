"""Kontrol service database: systemctl start/stop/restart per engine.

Map engine → nama unit systemd. Env override CCPANEL_<ENGINE>_SERVICE untuk
distro non-debian (mis. RHEL pakai mysqld/mariadb). Action valid:
start / stop / restart / reload. Status via is-active.
"""
from __future__ import annotations

import subprocess

SERVICES = {
    "mysql": "mariadb",
    "postgresql": "postgresql",
    "mongodb": "mongod",
    "redis": "redis-server",
}

ACTIONS = {"start", "stop", "restart", "reload", "status"}


def _unit(engine: str) -> str:
    env = f"CCPANEL_{engine.upper()}_SERVICE"
    import os

    return os.environ.get(env, SERVICES.get(engine, engine))


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=30)


def run(engine: str, action: str) -> dict:
    """Jalankan action systemctl. Return {ok, detail}. Action tak dikenal → error."""
    if action not in ACTIONS:
        return {"ok": False, "error": f"action tak dikenal: {action}"}
    unit = _unit(engine)
    res = _systemctl(action, unit)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip() or f"systemctl {action} {unit} gagal"
        return {"ok": False, "error": err}
    return {"ok": True, "detail": f"systemctl {action} {unit} ok"}


def status(engine: str) -> str:
    """Aktif/tidak. Return 'active' / 'inactive' / 'failed' / 'unknown'."""
    res = _systemctl("is-active", _unit(engine))
    return res.stdout.strip() or "unknown"
