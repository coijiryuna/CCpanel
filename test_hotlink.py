"""Unit test hotlink protection nginx (valid_referers per-site).
Jalankan:
    .venv/bin/python -m pytest test_hotlink.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import hotlink as hotlink_ops
from core import webserver as webserver_ops


def _inc_name() -> str:
    """Nama file include sesuai dir real (hotlink.d di prod, hotlink di test)."""
    return hotlink_ops.HOTLINK_DIR.name


def test_enable_disable():
    domain = "hot.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    hotlink_ops.enable(domain, vh)
    conf = vh.read_text()
    # include terpasang di vhost
    assert f"{_inc_name()}/hot.example.com.conf" in conf
    p = hotlink_ops.hotlink_path(domain)
    assert p.exists()
    text = p.read_text()
    assert "valid_referers none blocked server_names" in text
    assert "return 403" in text
    assert "location ~*" in text
    assert hotlink_ops.is_enabled(domain)

    hotlink_ops.disable(domain, vh)
    assert not hotlink_ops.is_enabled(domain)
    # include tetap ada (file penanda off)
    assert f"{_inc_name()}/hot.example.com.conf" in vh.read_text()
    assert hotlink_ops.hotlink_path(domain).read_text() == "# hotlink off\n"


def test_include_idempotent():
    """Enable dua kali tidak menambah include dobel di vhost."""
    domain = "hot2.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    hotlink_ops.enable(domain, vh)
    hotlink_ops.enable(domain, vh)
    conf = vh.read_text()
    assert conf.count(f"{_inc_name()}/hot2.example.com.conf") == 1
    assert conf.count("{") == conf.count("}"), "kurung tidak seimbang"


def test_apache_vhost_not_modified():
    """Vhost apache tidak boleh kena include hotlink (endpoint guard nginx-only)."""
    vh = Path(webserver_ops.for_engine("apache").vhost_path("apache-hot.example.com"))
    vh.parent.mkdir(parents=True, exist_ok=True)
    vh.write_text("<VirtualHost *:80>\n    ServerName apache-hot.example.com\n</VirtualHost>\n")
    hotlink_ops.enable("apache-hot.example.com", vh)
    assert "hotlink.d/" not in vh.read_text()
