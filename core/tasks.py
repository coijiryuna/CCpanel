"""Task system generik: proses background + buffer output per baris.

Dipakai appstore (install/uninstall) dan php extension install. Frontend
polling status via API. Status: running / done / error.
"""
from __future__ import annotations

import subprocess
import threading

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()

def start(key: str, fn) -> None:
    """Jalankan fn di thread daemon. fn dipanggil tanpa argumen."""
    t = threading.Thread(target=fn, daemon=True)
    t.start()

def append(key: str, line: str) -> None:
    with _LOCK:
        t = _TASKS.setdefault(key, {"status": "running", "lines": [], "error": "", "done": False})
        t["lines"].append(line)
        if len(t["lines"]) > 2000:
            t["lines"] = t["lines"][-2000:]

def finish(key: str, ok: bool, error: str = "") -> None:
    with _LOCK:
        t = _TASKS.setdefault(key, {"status": "running", "lines": [], "error": "", "done": False})
        t["status"] = "done" if ok else "error"
        t["error"] = error
        t["done"] = True

def status(key: str) -> dict:
    with _LOCK:
        t = _TASKS.get(key)
        if t is None:
            return {"status": "done", "lines": [], "error": "task not found", "done": True}
        return dict(t)

def list_active() -> list[dict]:
    with _LOCK:
        return [
            {"key": k, "status": v["status"], "done": v["done"]}
            for k, v in _TASKS.items() if not v["done"]
        ]

def run_stream(cmd: list[str], key: str, timeout: int = 1800) -> None:
    """Jalankan command, stream output baris per baris ke task key."""
    append(key, f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            bufsize=1,
        )
    except Exception as e:
        finish(key, False, str(e))
        return
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line:
                append(key, line)
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        finish(key, False, f"Timeout ({timeout}s)")
        return
    finish(key, rc == 0, "" if rc == 0 else f"exit code {rc}")