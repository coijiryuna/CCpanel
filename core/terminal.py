"""Terminal web: eksekusi perintah shell sebagai root.

Ini akses shell PENUH ke server — hanya untuk admin panel. Safety:
- timeout 15 detik (cegah perintah gantung)
- output dibatasi (cegah flood memory)
- deny list: perintah interaktif yang gantung di non-tty
- semua eksekusi dicatat ke audit trail (server.py)
"""
from __future__ import annotations

import subprocess

TIMEOUT = 15
MAX_OUTPUT = 200_000

# Perintah interaktif/hang di non-tty — tolak langsung.
# Prefix match untuk editor/pager/ssh. REPL (python/node tanpa argumen) match exact.
DENY_PREFIX = (
    "vim", "vi ", "nano", "top", "htop", "less", "more", "tail -f",
    "ssh ", "telnet", "mysql -", "psql",
)
DENY_EXACT = ("python", "python3", "node", "bash", "sh", "csh", "zsh")


class TerminalError(Exception):
    pass


def _blocked(cmd: str) -> bool:
    c = cmd.strip()
    if c in DENY_EXACT:
        return True
    for p in DENY_PREFIX:
        if c.startswith(p):
            return True
    return False


def exec_cmd(cmd: str) -> dict:
    """Jalankan perintah, return {output, exit_code}. Deny/timeout → TerminalError."""
    if not cmd.strip():
        raise TerminalError("Perintah kosong")
    if _blocked(cmd):
        raise TerminalError("Perintah interaktif/tidak aman untuk terminal web")
    try:
        res = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise TerminalError(f"Timeout ({TIMEOUT}s) — perintah dihentikan") from None
    out = (res.stdout or "") + (res.stderr or "")
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n... (output dipotong)"
    return {"output": out, "exit_code": res.returncode}
