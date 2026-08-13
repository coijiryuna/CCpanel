"""Unit test fitur per-site: URL rewrite, anti-XSS, access log, switch engine.
Jalankan:
    .venv/bin/python -m pytest test_siteconfig.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import siteconfig as sc
from core import webserver as webserver_ops


def test_rewrite_set_get_clear():
    domain = "rw.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    assert sc.rewrite_rules(domain) == ""
    sc.set_rewrite(domain, "rewrite ^/old$ /new permanent;", vh)
    assert "rewrite ^/old$ /new permanent;" in sc.rewrite_rules(domain)
    # include terpasang di vhost
    assert "sitefeat" in vh.read_text()
    # update ganti rules, tidak dobel
    sc.set_rewrite(domain, "rewrite ^/a$ /b last;", vh)
    rules = sc.rewrite_rules(domain)
    assert "rewrite ^/a$ /b last;" in rules
    assert "old" not in rules
    # kosongkan = blok hilang
    sc.set_rewrite(domain, "", vh)
    assert sc.rewrite_rules(domain) == ""


def test_xss_toggle():
    domain = "xss.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    assert not sc.xss_enabled(domain)
    sc.set_xss(domain, True, vh)
    assert sc.xss_enabled(domain)
    text = sc.feat_path(domain).read_text()
    assert "return 403" in text
    assert "<script" in text or "script" in text
    sc.set_xss(domain, False, vh)
    assert not sc.xss_enabled(domain)


def test_accesslog_toggle():
    domain = "log.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    # default on
    assert sc.accesslog_enabled(domain)
    sc.set_accesslog(domain, False, vh)
    assert not sc.accesslog_enabled(domain)
    assert "access_log off;" in sc.feat_path(domain).read_text()
    sc.set_accesslog(domain, True, vh)
    assert sc.accesslog_enabled(domain)


def test_state():
    domain = "st.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)
    sc.set_rewrite(domain, "rewrite ^/x$ /y permanent;", vh)
    st = sc.state(domain)
    assert st["rewrite_rules"]
    assert st["xss_enabled"] is False
    assert st["accesslog_enabled"] is True


def test_nginx_create_site_with_running_dir():
    domain = "runningdir.example.com"
    running_dir = "public_html"
    webserver_ops.for_engine("nginx").create_site(domain, running_dir=running_dir)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)
    assert vh.exists()
    content = vh.read_text()
    assert f"root {webserver_ops.for_engine('nginx').root_path(domain)}/{running_dir};" in content
