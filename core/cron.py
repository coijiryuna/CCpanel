"""Cron job: auto-renew SSL (certbot) via crontab root.

Install: tulis script wrapper (root-only) + line crontab. Script jalan
`certbot renew --nginx --non-interactive`, reload nginx kalau sukses, dan
mencatat hasil ke data/ssl-renew.log. Uninstall: hapus line + script.
Semua path bisa dioverride via env (CCPANEL_CRON_CMD, CCPANEL_DATA_DIR,
CCPANEL_CRON_LOG) supaya bisa diuji tanpa root.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CCPANEL_DATA_DIR", BASE_DIR / "data"))
SCRIPT_PATH = Path(os.environ.get("CCPANEL_CRON_SCRIPT", BASE_DIR / "scripts" / "ccpanel-renew.sh"))
LOG_PATH = Path(os.environ.get("CCPANEL_CRON_LOG", DATA_DIR / "ssl-renew.log"))
CRON_CMD = os.environ.get("CCPANEL_CRON_CMD", "certbot renew --nginx --non-interactive")
CRON_MARKER = "ccpanel-ssl-renew"
CRON_SCHEDULE = "0 3 * * *"
CRON_LINE = f"{CRON_SCHEDULE} {SCRIPT_PATH} >> {LOG_PATH} 2>&1  # {CRON_MARKER}"

SCRIPT_TEMPLATE = """#!/bin/sh
# CCPanel: auto-renew SSL certbot (dikelola panel — jangan edit manual).
# PATH di-set eksplisit: cron pakai PATH minimal, certbot/systemctl sering di /usr/bin.
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Berhenti kalau ada instance lain jalan (crontab lama + klik manual).
if [ -f {log}.lock ]; then
    echo "$(date -Is) SKIP: lock ada" >> {log}
    exit 0
fi
: > {log}.lock
trap 'rm -f {log}.lock' EXIT
if {cmd}; then
    systemctl reload nginx
    echo "$(date -Is) OK: renew selesai, nginx reloaded" >> {log}
else
    echo "$(date -Is) FAIL: certbot renew gagal (cek log certbot)" >> {log}
    exit 1
fi
"""


class CronError(Exception):
    pass


def _crontab(args: list[str], input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["crontab", *args], input=input, capture_output=True, text=True)


def _current() -> str:
    res = _crontab(["-l"], input="")
    if res.returncode != 0:
        # crontab -l exit 1 = belum ada crontab sama sekali — treat as empty
        if "no crontab" in (res.stderr or "").lower() or not (res.stderr or "").strip():
            return ""
        raise CronError(res.stderr.strip() or "crontab -l failed")
    return res.stdout


def status() -> dict:
    return {"installed": CRON_MARKER in _current()}


def install() -> dict:
    """Tulis script + tambah line crontab. Idempoten (no-op kalau sudah ada)."""
    SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    script = SCRIPT_TEMPLATE.format(log=LOG_PATH, cmd=CRON_CMD)
    SCRIPT_PATH.write_text(script)
    SCRIPT_PATH.chmod(0o700)

    current = _current()
    if CRON_MARKER in current:
        return {"ok": True, "installed": True, "script": str(SCRIPT_PATH)}
    new = (current.rstrip() + "\n" + CRON_LINE + "\n") if current else CRON_LINE + "\n"
    res = _crontab(["-"], input=new)
    if res.returncode != 0:
        raise CronError(res.stderr.strip() or "crontab - failed")
    return {"ok": True, "installed": True, "script": str(SCRIPT_PATH)}


def uninstall() -> dict:
    """Hapus line crontab + script. Idempoten."""
    current = _current()
    if CRON_MARKER in current:
        kept = [ln for ln in current.splitlines() if CRON_MARKER not in ln]
        res = _crontab(["-"], input="\n".join(kept) + "\n")
        if res.returncode != 0:
            raise CronError(res.stderr.strip() or "crontab - failed")
    SCRIPT_PATH.unlink(missing_ok=True)
    return {"ok": True, "installed": False}
