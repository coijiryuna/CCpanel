"""Input sanitasi — semua input dari API harus lewat sini dulu."""
from __future__ import annotations

import re

# Domain: label dipisah titik, tiap label 1-63 char, total max 253.
# Lowercase + digit + hyphen saja (punycode `xn--` lolos sebagai label valid).
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
)
# Nama DB/user MySQL: lowercase + underscore, max 64 (batas MySQL).
DB_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
IP_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")
IPV6_RE = re.compile(r"^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$")


def valid_domain(domain: str) -> bool:
    return bool(DOMAIN_RE.fullmatch(domain))


def valid_db_name(name: str) -> bool:
    return bool(DB_NAME_RE.fullmatch(name))

def valid_ip(ip: str) -> bool:
    m = IP_RE.fullmatch(ip)
    if m and all(0 <= int(o) <= 255 for o in m.groups()):
        return True
    return bool(IPV6_RE.fullmatch(ip))
