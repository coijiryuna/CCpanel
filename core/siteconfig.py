"""Fitur per-site (nginx): URL rewrite, anti-XSS, access log.

Semua pakai pola include-file (sama WAF/hotlink): vhost berisi
`include {DIR}/{domain}.conf;`, file berisi blok fitur. Toggle/tulis file
tanpa ubah vhost manual — _ensure_include sisip otomatis kalau belum ada.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

CONF_DIR = Path(os.environ.get("CCPANEL_SITEFEAT_DIR", "/etc/nginx/sitefeat.d"))

class Error(Exception):
    pass

REWRITE_BEGIN = "# BEGIN CCPANEL REWRITE"
REWRITE_END = "# END CCPANEL REWRITE"
LOG_BEGIN = "# BEGIN CCPANEL ACCESSLOG"
LOG_END = "# END CCPANEL ACCESSLOG"
XSS_BEGIN = "# BEGIN CCPANEL XSS"
XSS_END = "# END CCPANEL XSS"

INCLUDE_RE = re.compile(r"include\s+\S*sitefeat[^/]*/\S*;")


def feat_path(domain: str) -> Path:
    return CONF_DIR / f"{domain}.conf"


def _ensure_include(vhost: Path, domain: str | None = None) -> None:
    """Pastikan vhost menginclude file fitur domain ini. Sisip sebelum `}` penutup.

    domain: nama domain (untuk vhost proxy project `proj-<domain>.conf` yang
    stem-nya beda dari nama file fitur). Kalau None, pakai vhost.stem (site).
    """
    if not vhost.exists():
        return
    text = vhost.read_text(encoding="utf-8")
    if INCLUDE_RE.search(text):
        return
    name = domain if domain is not None else vhost.stem
    inc = f"    include {CONF_DIR / name}.conf;\n"
    idx = text.rstrip().rfind("}")
    if idx == -1:
        return
    vhost.write_text(text[:idx] + inc + text[idx:], encoding="utf-8")


# --------------------------------------------------------------- URL rewrite
def rewrite_rules(domain: str) -> str:
    """Rules rewrite yang tersimpan (tanpa marker). Kosong = belum ada."""
    p = feat_path(domain)
    if not p.exists():
        return ""
    m = re.search(rf"{re.escape(REWRITE_BEGIN)}\n(.*?)\n{re.escape(REWRITE_END)}", p.read_text(encoding="utf-8"), re.DOTALL)
    return m.group(1).strip() if m else ""


def set_rewrite(domain: str, rules: str, vhost: Path | None = None, vhost_domain: str | None = None) -> None:
    """Simpan rules rewrite. Rules kosong = hapus blok (fitur nonaktif).

    vhost_domain: nama domain utk include (vhost proxy project `proj-<d>.conf`
    stem-nya beda). None = pakai vhost.stem (site biasa).
    """
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost, vhost_domain)
    p = feat_path(domain)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    # buang blok rewrite lama
    text = re.sub(rf"\s*{re.escape(REWRITE_BEGIN)}.*?{re.escape(REWRITE_END)}\s*", "\n", text, flags=re.DOTALL)
    rules = (rules or "").strip()
    if rules:
        body = "\n".join("    " + ln for ln in rules.splitlines() if ln.strip())
        block = f"{REWRITE_BEGIN}\n{body}\n{REWRITE_END}\n"
        text = text.rstrip() + "\n" + block
    p.write_text(text.strip() + "\n")


# ----------------------------------------------------------------- anti-XSS
XSS_RULES = [
    r"(<script[\s>])",
    r"(\bon(error|load|click|mouseover|submit|focus|blur)\s*=)",
    r"(javascript\s*:)",
    r"(<iframe[\s>])",
    r"(<object[\s>])",
    r"(<embed[\s>])",
    r"(<svg[\s>])",
    r"(<math[\s>])",
]
XSS_TPL = '    if ($request_uri ~* {pattern}) {{ return 403; }}\n'
XSS_OFF = "# xss off\n"


def xss_enabled(domain: str) -> bool:
    p = feat_path(domain)
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8")
    if re.search(rf"{re.escape(XSS_BEGIN)}", text):
        return True
    return False


def set_xss(domain: str, enabled: bool, vhost: Path | None = None, vhost_domain: str | None = None) -> None:
    """Toggle anti-XSS. Rules = subset XSS dari WAF, cek $request_uri."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost, vhost_domain)
    p = feat_path(domain)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    # buang blok xss lama + penanda off
    text = re.sub(rf"\s*{re.escape(XSS_BEGIN)}.*?{re.escape(XSS_END)}\s*", "\n", text, flags=re.DOTALL)
    text = re.sub(rf"\s*{re.escape(XSS_OFF)}\s*", "\n", text)
    if enabled:
        body = "".join(XSS_TPL.format(pattern=r) for r in XSS_RULES)
        block = f"{XSS_BEGIN}\n{body}{XSS_END}\n"
        text = text.rstrip() + "\n" + block
    else:
        text = text.rstrip() + "\n" + XSS_OFF
    p.write_text(text.strip() + "\n")


# ------------------------------------------------------------- access log
LOG_OFF = "# accesslog off\n"


def accesslog_enabled(domain: str) -> bool:
    p = feat_path(domain)
    if not p.exists():
        return True  # default nginx: access log on
    text = p.read_text(encoding="utf-8")
    return not (re.search(rf"{re.escape(LOG_BEGIN)}", text) and "off" in text)


def set_accesslog(domain: str, enabled: bool, vhost: Path | None = None, vhost_domain: str | None = None) -> None:
    """Toggle access log per-site. Off = `access_log off;` di server block."""
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    if vhost is not None:
        _ensure_include(vhost, vhost_domain)
    p = feat_path(domain)
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    # buang blok log lama + penanda
    text = re.sub(rf"\s*{re.escape(LOG_BEGIN)}.*?{re.escape(LOG_END)}\s*", "\n", text, flags=re.DOTALL)
    text = re.sub(rf"\s*{re.escape(LOG_OFF)}\s*", "\n", text)
    if enabled:
        # aktif = hapus blok off (nginx default access_log on)
        pass
    else:
        block = f"{LOG_BEGIN}\n    access_log off;\n{LOG_END}\n"
        text = text.rstrip() + "\n" + block
    p.write_text(text.strip() + "\n")


def state(domain: str) -> dict:
    """State semua fitur untuk GET config."""
    return {
        "rewrite_rules": rewrite_rules(domain),
        "xss_enabled": xss_enabled(domain),
        "accesslog_enabled": accesslog_enabled(domain),
    }


def migrate_vhost(domain: str, old_content: str, new_vhost: Path, engine: str = "nginx") -> None:
    """Pindahkan include fitur dari vhost lama ke vhost baru (switch engine).

    old_content: isi vhost lama. new_vhost: vhost engine baru.
    Include sitefeat HANYA syntax nginx. Saat switch ke apache/litespeed,
    include TIDAK disalin (fitur rewrite/xss/accesslog memang nginx-only).
    File fitur sendiri tetap di sitefeat.d. Kalau balik ke nginx, include
    di-restore selama file fitur masih punya konten.
    """
    if not new_vhost.exists():
        return
    if engine != "nginx":
        return
    # kalau vhost lama punya include → salin (switch nginx→nginx path tak dipakai,
    # tapi jaga-jaga). Kalau tidak, restore dari file fitur yang masih ada.
    m = re.search(r"include\s+\S*sitefeat[^/]*/\S*;", old_content)
    if m:
        inc = m.group(0)
    else:
        p = feat_path(domain)
        if not p.exists() or not p.read_text(encoding="utf-8").strip():
            return
        inc = f"    include {CONF_DIR / domain}.conf;"
    text = new_vhost.read_text(encoding="utf-8")
    if INCLUDE_RE.search(text):
        return
    idx = text.rstrip().rfind("}")
    if idx == -1:
        return
    new_vhost.write_text(text[:idx] + "\n    " + inc + "\n" + text[idx:], encoding="utf-8")
