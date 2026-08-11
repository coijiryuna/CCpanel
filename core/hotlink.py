"""Hotlink protection nginx: blok `valid_referers` per-site diinclude dari vhost.

Design: vhost berisi `include {HOTLINK_DIR}/{domain}.conf;`. File berisi
`location ~* \.(gif|jpg|...)$ { valid_referers ...; if ($invalid_referer) { return 403; } }`
atau `# hotlink off` kalau nonaktif. Toggle = tulis file (bukan ubah vhost) + reload.

Referrer yang diizinkan: `none` (buka langsung), `blocked` (referrer tanpa host),
`server_names` (semua domain di vhost ini). Domain eksternal lain → 403.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

HOTLINK_DIR = Path(os.environ.get("CCPANEL_HOTLINK_DIR", "/etc/nginx/hotlink.d"))

# Ekstensi aset yang rawan di-leech (gambar, media, dokumen, font, css/js).
EXTENSIONS = (
    "gif|jpg|jpeg|png|webp|svg|bmp|ico|avif|"
    "css|js|woff|woff2|ttf|eot|otf|"
    "mp3|mp4|avi|mkv|mov|wmv|flv|webm|m4a|aac|ogg|"
    "pdf|zip|rar|7z|gz|tar|doc|docx|xls|xlsx|ppt|pptx"
)

BLOCK_TPL = """    location ~* \\.({exts})$ {{
        valid_referers none blocked server_names;
        if ($invalid_referer) {{
            return 403;
        }}
    }}
"""
OFF_COMMENT = "# hotlink off\n"
INCLUDE_RE = re.compile(r"include\s+\S*hotlink[^/]*/\S*;")


def hotlink_path(domain: str) -> Path:
    return HOTLINK_DIR / f"{domain}.conf"


def _ensure_include(vhost: Path) -> None:
    """Pastikan vhost menginclude file hotlink domain ini. Sisip sebelum `}` penutup."""
    if not vhost.exists():
        return
    text = vhost.read_text(encoding="utf-8")
    if INCLUDE_RE.search(text):
        return
    inc = f"    include {HOTLINK_DIR / vhost.stem}.conf;\n"
    # sisip sebelum kurung tutup terakhir (server block)
    idx = text.rstrip().rfind("}")
    if idx == -1:
        return
    vhost.write_text(text[:idx] + inc + text[idx:], encoding="utf-8")


def enable(domain: str, vhost: Path | None = None) -> None:
    """Tulis blok valid_referers + pastikan include."""
    HOTLINK_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost)
    body = BLOCK_TPL.format(exts=EXTENSIONS)
    hotlink_path(domain).write_text(body)


def disable(domain: str, vhost: Path | None = None) -> None:
    """Tulis penanda nonaktif. File tetap ada biar include valid."""
    HOTLINK_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost)
    hotlink_path(domain).write_text(OFF_COMMENT)


def is_enabled(domain: str) -> bool:
    p = hotlink_path(domain)
    if not p.exists():
        return False
    return p.read_text(encoding="utf-8").strip() != OFF_COMMENT.strip()
