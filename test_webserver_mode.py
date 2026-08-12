"""Test arsitektur multi-web-server (aaPanel): nginx front + backend port.

Mode single: engine aktif pegang 80/443.
Mode multi : nginx front 80 proxy -> backend 8288 (apache) / 8188 (OLS).

Jalankan:
    .venv/bin/python -m pytest test_webserver_mode.py
"""
import os
from pathlib import Path

from core import apache as apache_ops
from core import nginx as nginx_ops
from core import webserver as webserver_ops

def _domain(name: str) -> str:
    return f"{name}.example.com"

def _nginx_vhost(domain: str) -> Path:
    return nginx_ops.vhost_path(domain)

# ------------------------------------------------------------------ mode flag

def test_mode_default_single():
    """Default mode = single kalau env tak diset."""
    assert webserver_ops.mode() == "single"
    assert not webserver_ops.is_multi()

def test_set_mode(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    assert webserver_ops.mode() == "multi"
    assert webserver_ops.is_multi()
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "single")
    assert webserver_ops.mode() == "single"

def test_backend_ports():
    assert webserver_ops.backend_port("apache") == 8288
    assert webserver_ops.backend_port("litespeed") == 8188
    assert webserver_ops.backend_port("nginx") == 80

# ------------------------------------------------------- apache listen port

def test_apache_single_listen_80(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "single")
    assert apache_ops._listen_port() == 80

def test_apache_multi_listen_8288(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    assert apache_ops._listen_port() == 8288

def test_apache_vhost_port_multi(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("apmulti")
    vh = apache_ops.vhost_path(domain)
    vh.parent.mkdir(parents=True, exist_ok=True)
    root = apache_ops.root_path(domain)
    root.mkdir(parents=True, exist_ok=True)
    apache_ops._write_vhost(domain, root)
    text = vh.read_text()
    assert "<VirtualHost *:8288>" in text
    assert "<VirtualHost *:80>" not in text

def test_apache_ensure_listen_multi(monkeypatch, tmp_path):
    """Multi mode: ports.conf otomatis dapat `Listen 8288`."""
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    ports = tmp_path / "ports.conf"
    ports.write_text("Listen 80\n")
    monkeypatch.setattr(apache_ops, "APACHE_PORTS_CONF", ports)
    apache_ops._ensure_listen(8288)
    assert "Listen 8288" in ports.read_text()
    # idempotent — tidak dobel
    apache_ops._ensure_listen(8288)
    assert ports.read_text().count("Listen 8288") == 1

def test_apache_ensure_listen_single(monkeypatch, tmp_path):
    """Single mode: _ensure_listen(80) tidak sentuh ports.conf."""
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "single")
    ports = tmp_path / "ports.conf"
    ports.write_text("Listen 80\n")
    monkeypatch.setattr(apache_ops, "APACHE_PORTS_CONF", ports)
    apache_ops._ensure_listen(80)
    assert ports.read_text() == "Listen 80\n"

# ------------------------------------------------------------- front proxy

def test_front_proxy_enable(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("front1")
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = _nginx_vhost(domain)

    # site backend: nginx vhost jadi front proxy -> 8288
    webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port("apache"))
    conf = vh.read_text()
    assert "listen 80;" in conf
    assert "proxy_pass http://127.0.0.1:8288;" in conf
    assert "try_files" not in conf
    assert conf.count("{") == conf.count("}"), "kurung tidak seimbang"

def test_front_proxy_disable(monkeypatch):
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("front2")
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = _nginx_vhost(domain)

    webserver_ops.front_proxy_enable(domain, 8188)
    assert "proxy_pass http://127.0.0.1:8188;" in vh.read_text()

    # balik ke static
    webserver_ops.front_proxy_disable(domain)
    conf = vh.read_text()
    assert "proxy_pass" not in conf
    assert "try_files $uri $uri/ =404;" in conf
    assert "listen 80;" in conf

def test_front_proxy_enable_overwrite(monkeypatch):
    """front_proxy_enable timpa vhost lama (static/proxy) — idempotent."""
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("front3")
    webserver_ops.for_engine("nginx").create_site(domain)
    webserver_ops.front_proxy_enable(domain, 8288)
    webserver_ops.front_proxy_enable(domain, 8288)
    conf = _nginx_vhost(domain).read_text()
    assert conf.count("proxy_pass http://127.0.0.1:8288;") == 1
    assert conf.count("{") == conf.count("}")

def test_front_proxy_preserve_ssl(monkeypatch):
    """SSL (443 + ssl_*) dari vhost lama di-preserve saat front proxy
    ditimpa — site backend tetap HTTPS setelah switch engine."""
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("ssl1")
    vh = _nginx_vhost(domain)
    vh.parent.mkdir(parents=True, exist_ok=True)
    vh.write_text(
        "server {\n"
        "    listen 80;\n"
        "    listen 443 ssl http2;\n"
        "    server_name ssl1.example.com;\n"
        "    ssl_certificate /etc/letsencrypt/live/ssl1.example.com/fullchain.pem;\n"
        "    ssl_certificate_key /etc/letsencrypt/live/ssl1.example.com/privkey.pem;\n"
        "    location / { try_files $uri $uri/ =404; }\n"
        "}\n"
    )
    webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port("apache"))
    conf = vh.read_text()
    assert "proxy_pass http://127.0.0.1:8288;" in conf
    assert "listen 443 ssl http2;" in conf
    assert "ssl_certificate /etc/letsencrypt/live/ssl1.example.com/fullchain.pem;" in conf
    assert "ssl_certificate_key /etc/letsencrypt/live/ssl1.example.com/privkey.pem;" in conf
    assert conf.count("{") == conf.count("}"), "kurung tidak seimbang"

# ------------------------------------------------- create_site multi: backend

def test_create_site_backend_multi(monkeypatch):
    """Site backend (apache) di multi mode: vhost apache 8288 + front proxy 80."""
    monkeypatch.setenv("CCPANEL_WEBSERVER_MODE", "multi")
    domain = _domain("backend1")
    eng = webserver_ops.for_engine("apache")
    root = eng.create_site(domain)
    webserver_ops.front_proxy_enable(domain, webserver_ops.backend_port("apache"))

    assert "<VirtualHost *:8288>" in eng.vhost_path(domain).read_text()
    front = _nginx_vhost(domain).read_text()
    assert "proxy_pass http://127.0.0.1:8288;" in front
    assert root.is_dir()
