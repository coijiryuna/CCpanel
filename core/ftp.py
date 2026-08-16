"""Operasi FTP vsftpd: akun virtual user per site, chroot ke folder site.

Pendekatan: vsftpd virtual users (PAM + user_db, tanpa useradd sistem).
Tiap akun: username unik, password, site_id, local_root = folder site.
File konfigurasi vsftpd dioverride via env CCPANEL_FTP_CONF_DIR untuk test.
"""
from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

from . import validate

FTP_CONF_DIR = Path(os.environ.get("CCPANEL_FTP_CONF_DIR", "/etc/vsftpd"))
USER_DB = FTP_CONF_DIR / "user_db"
PASSWD_FILE = FTP_CONF_DIR / "passwd"

class FtpError(Exception):
    pass

def _generate_password() -> str:
    return secrets.token_urlsafe(12)

def _write_passwd(accounts: list[tuple[str, str]]) -> None:
    """Tulis file passwd (username<tab>password) lalu db_load.

    Atomic: tulis ke temp dulu, db_load baru commit ke PASSWD_FILE.
    Kalau db_load gagal, file lama tidak berubah.
    """
    FTP_CONF_DIR.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{u}\t{p}\n" for u, p in accounts)
    tmp = FTP_CONF_DIR / "passwd.tmp"
    tmp.write_text(lines, encoding="utf-8")
    try:
        res = subprocess.run(["db_load", "-T", "-t", "hash", "-f", str(tmp), str(USER_DB)], capture_output=True, text=True)
    except FileNotFoundError:
        res = None
    if res is not None and res.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise FtpError(res.stderr.strip() or "db_load gagal")
    if res is None:
        PASSWD_FILE.write_text(lines, encoding="utf-8")
        tmp.unlink(missing_ok=True)
        return
    tmp.rename(PASSWD_FILE)

def _load_accounts() -> list[tuple[str, str]]:
    """Baca akun dari PASSWD_FILE (kalau ada)."""
    if not PASSWD_FILE.exists():
        return []
    out = []
    for line in PASSWD_FILE.read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            u, p = line.split("\t", 1)
            out.append((u, p))
    return out

def create_account(username: str, password: str, site_id: int) -> str:
    """Buat akun FTP. Password kosong = random. Simpan ke user_db."""
    if not validate.valid_db_name(username):
        raise FtpError("Username tidak valid (a-z, 0-9, _, max 64)")
    password = (password or _generate_password()).strip()
    if not password or len(password) > 128:
        raise FtpError("Password tidak valid (1-128 char)")
    accounts = _load_accounts()
    if any(u == username for u, _ in accounts):
        raise FtpError("Akun FTP sudah ada")
    accounts.append((username, password))
    _write_passwd(accounts)
    return password

def delete_account(username: str) -> None:
    """Hapus akun FTP dari user_db."""
    if not validate.valid_db_name(username):
        raise FtpError("Username tidak valid")
    accounts = _load_accounts()
    kept = [(u, p) for u, p in accounts if u != username]
    if len(kept) == len(accounts):
        raise FtpError("Akun FTP tidak ada")
    _write_passwd(kept)

def reset_password(username: str, password: str) -> str:
    """Ganti password akun FTP. Password kosong = random."""
    if not validate.valid_db_name(username):
        raise FtpError("Username tidak valid")
    password = (password or _generate_password()).strip()
    if not password or len(password) > 128:
        raise FtpError("Password tidak valid (1-128 char)")
    accounts = _load_accounts()
    found = False
    for i, (u, p) in enumerate(accounts):
        if u == username:
            accounts[i] = (u, password)
            found = True
            break
    if not found:
        raise FtpError("Akun FTP tidak ada")
    _write_passwd(accounts)
    return password
