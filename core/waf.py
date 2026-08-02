"""WAF nginx: rules per-site diinclude dari vhost.

Design: vhost berisi `include {WAF_DIR}/{domain}.conf;`. File itu berisi
`if ($request_uri ~* ...) { return 403; }` rules, atau `# waf off` kalau
nonaktif. Toggle = tulis file (bukan ubah vhost) + reload.

Site lama (vhost tanpa include): enable/disable sisipkan baris include
otomatis sebelum `}` penutup — migrasi tanpa recreate.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

WAF_DIR = Path(os.environ.get("CCPANEL_WAF_DIR", "/etc/nginx/waf.d"))

# Pola dikelompokkan biar gampang dibaca. Semua case-insensitive.
RULES = [
    # SQL injection: union select, sleep, information_schema, dll.
    r"(\bunion\s+(all\s+)?select\b)",
    r"(\bsleep\s*\()",
    r"(information_schema\.)",
    r"(\b(select|insert|update|delete|drop|alter)\s+(from|into|table|database)\b)",
    r"(--|/\*!|#\s*\d)",
    # XSS: tag script, onerror/onload, javascript:
    r"(<script[\s>])",
    r"(\bon(error|load|click|mouseover)\s*=)",
    r"(javascript\s*:)",
    # Path traversal
    r"(\.\./|\.\.\\|/etc/passwd)",
    # Command injection
    r"(\$\s*\(|\b(rm|wget|curl|nc|bash|sh)\s+-[a-z]+\s)",
]

RULE_TPL = '    if ($request_uri ~* {pattern}) {{ return 403; }}\n'
OFF_COMMENT = "# waf off\n"
INCLUDE_RE = re.compile(r"include\s+\S*waf\.d/\S*;")

def waf_path(domain: str) -> Path:
    return WAF_DIR / f"{domain}.conf"

def _ensure_include(vhost: Path) -> None:
    """Pastikan vhost menginclude file WAF domain ini. Sisip sebelum `}` penutup."""
    if not vhost.exists():
        return
    text = vhost.read_text(encoding="utf-8")
    if INCLUDE_RE.search(text):
        return
    inc = f"    include {WAF_DIR / vhost.stem}.conf;\n"
    # sisip sebelum kurung tutup terakhir (server block)
    idx = text.rstrip().rfind("}")
    if idx == -1:
        return
    vhost.write_text(text[:idx] + inc + text[idx:], encoding="utf-8")

def enable(domain: str, vhost: Path | None = None) -> None:
    """Tulis rules + pastikan include + (opsional) migrasi vhost lama."""
    WAF_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost)
    body = "".join(RULE_TPL.format(pattern=p) for p in RULES)
    waf_path(domain).write_text(body)

def disable(domain: str, vhost: Path | None = None) -> None:
    """Tulis penanda nonaktif. File tetap ada biar include valid."""
    WAF_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost)
    waf_path(domain).write_text(OFF_COMMENT)

def is_enabled(domain: str) -> bool:
    p = waf_path(domain)
    if not p.exists():
        return False
    return p.read_text(encoding="utf-8").strip() != OFF_COMMENT.strip()

