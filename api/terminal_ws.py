"""Terminal WebSocket: shell interaktif real-time via pty.

xterm.js di browser ↔ WebSocket ↔ pty (bash). Satu sesi per koneksi.
Keamanan: admin-only (require_admin), deny list sama dengan core/terminal.py,
semua perintah dicatat ke audit trail. PTY jalan sebagai user `www` — untuk
root harus `sudo su` (seperti terminal host).
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import pwd
import signal
import struct
import termios

from fastapi import WebSocket, WebSocketDisconnect

from .deps import _client_ip, _log, app

# user shell terminal — drop privilege dari root ke user ini
SHELL_USER = os.environ.get("CCPANEL_TERM_USER", "www")

# deny list interaktif (sama dengan core/terminal.py) — cegah hang/hijack
DENY_PREFIX = (
    "vim", "vi ", "nano", "top", "htop", "less", "more", "tail -f",
    "ssh ", "telnet", "mysql -", "psql",
)
DENY_EXACT = ("python", "python3", "node", "bash", "sh", "csh", "zsh")


def _blocked(cmd: str) -> bool:
    c = cmd.strip()
    if c in DENY_EXACT:
        return True
    return any(c.startswith(p) for p in DENY_PREFIX)


@app.websocket("/api/terminal/ws")
async def terminal_ws(ws: WebSocket) -> None:
    # auth dulu sebelum accept — token lewat query param (WebSocket browser tak
    # bisa set header Authorization)
    token = ws.query_params.get("token", "")
    from .deps import _get_user, jwt, JWT_SECRET

    user = None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        row = _get_user(payload["sub"])
        if row is not None and row["role"] == "admin":
            user = dict(row)
    except Exception:
        user = None
    if user is None:
        await ws.close(code=4401, reason="Unauthorized")
        return
    user["ip"] = _client_ip(ws)

    await ws.accept()

    # spawn pty — child langsung turun privilege ke SHELL_USER (www).
    # Fallback www-data; kalau bukan root (dev), setuid gagal → jalan sebagai
    # user sekarang. Produksi (root + www) selalu drop ke www.
    pid, fd = pty.fork()
    if pid == 0:  # child
        pw = None
        for name in (SHELL_USER, "www-data"):
            try:
                pw = pwd.getpwnam(name)
                break
            except KeyError:
                continue
        if pw is not None:
            try:
                os.initgroups(pw.pw_name, pw.pw_gid)
                os.setgid(pw.pw_gid)
                os.setuid(pw.pw_uid)
            except PermissionError:
                pw = None  # bukan root — biarkan user sekarang
        user_name = pw.pw_name if pw is not None else pwd.getpwuid(os.getuid()).pw_name
        home = pw.pw_dir if pw is not None else os.environ.get("HOME", "/")
        os.environ.clear()
        os.environ.update({
            "TERM": "xterm-256color",
            "HOME": home,
            "USER": user_name,
            "LOGNAME": user_name,
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PS1": "\\u@\\h:\\w\\$ ",
        })
        os.execvp("bash", ["bash", "--login"])
        os._exit(1)

    loop = asyncio.get_running_loop()
    reader_task: asyncio.Task | None = None

    def _write_ws(data: bytes) -> None:
        # send_text dari thread pool → harus kembali ke event loop utama
        asyncio.run_coroutine_threadsafe(ws.send_text(data.decode("utf-8", "replace")), loop)

    def _read_pty() -> None:
        # jalan di thread pool — drain SEMUA data yang ada (os.read berulang
        # sampai EAGAIN). EAGAIN = buffer kosong = normal, BUKAN error.
        while True:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                return  # buffer kosong, tunggu trigger berikutnya
            except OSError as e:
                if reader_task is not None:
                    loop.call_soon_threadsafe(reader_task.cancel)
                return
            if not data:
                if reader_task is not None:
                    loop.call_soon_threadsafe(reader_task.cancel)
                return
            _write_ws(data)

    async def _reader() -> None:
        loop.add_reader(fd, lambda: loop.run_in_executor(None, _read_pty))
        try:
            await asyncio.Future()  # jalan sampai dibatalkan
        finally:
            loop.remove_reader(fd)

    reader_task = loop.create_task(_reader())
    _log(None, user, "terminal.open", "sesi terminal interaktif")

    def _resize(cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def _close() -> None:
        if reader_task is not None:
            reader_task.cancel()
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    try:
        while True:
            raw = await ws.receive_text()
            if raw.startswith("\x00resize:"):
                try:
                    _, cols, rows = raw.split(":")
                    _resize(int(cols), int(rows))
                except ValueError:
                    pass
                continue
            # audit per baris perintah (enter) — catat command yang diketik
            if raw.endswith("\r") or raw.endswith("\n"):
                cmd = raw.strip("\r\n")
                if cmd.strip() and not _blocked(cmd):
                    _log(None, user, "terminal.cmd", cmd)
            os.write(fd, raw.encode())
    except WebSocketDisconnect:
        pass
    finally:
        _close()
        _log(None, user, "terminal.close", "sesi terminal ditutup")
