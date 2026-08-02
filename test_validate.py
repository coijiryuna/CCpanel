"""Unit test validasi input + path traversal guard. Jalankan:
    .venv/bin/python -m pytest test_validate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.validate import valid_db_name, valid_domain, valid_ip


def test_domain_valid():
    for d in ["example.com", "sub.example.com", "xn--bcher-kva.example", "a-b.c-d.co.id", "localhost.localdomain"]:
        assert valid_domain(d), d


def test_domain_invalid():
    for d in ["bad domain", "-lead.com", "trail-.com", "exa mple.com", "a..b.com", "", ".com", "exa_mple.com", "UPPER.com", "localhost", "a" * 64 + ".com"]:
        assert not valid_domain(d), d


def test_db_name_valid():
    for n in ["app", "app_web", "a1_b2", "x" * 64]:
        assert valid_db_name(n), n


def test_db_name_invalid():
    for n in ["App", "app-web", "app.web", "a b", "", "x" * 65, "app$"]:
        assert not valid_db_name(n), n

def test_ip_valid():
    for ip in ["127.0.0.1", "0.0.0.0", "255.255.255.255", "192.168.1.10"]:
        assert valid_ip(ip), ip

def test_ip_invalid():
    for ip in ["256.1.1.1", "1.2.3", "1.2.3.4.5", "a.b.c.d", "1.2.3.-1", "", "300.1.1.1"]:
        assert not valid_ip(ip), ip


def test_path_traversal():
    from api.files import _resolve_within
    from fastapi import HTTPException

    root = Path("/tmp/ccp-root")
    ok = _resolve_within(root, "sub/file.txt")
    assert str(ok) == "/tmp/ccp-root/sub/file.txt"
    ok = _resolve_within(root, "")
    assert str(ok) == "/tmp/ccp-root"
    # `..%2f` sudah didecode Starlette sebelum sampai handler → tes literal ../ cukup
    for bad in ["../../etc/passwd", "..", "../..", "sub/../../etc", "/etc/passwd"]:
        try:
            _resolve_within(root, bad)
        except HTTPException:
            continue
        raise AssertionError(f"traversal lolos: {bad}")
