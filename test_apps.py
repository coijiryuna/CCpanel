"""Unit test app runner (systemd unit + docker compose) dan proxy subpath nginx.
Jalankan:
    .venv/bin/python -m pytest test_apps.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import apps as apps_ops
from core import nginx as nginx_ops
from core import webserver as webserver_ops


def test_unit_create():
    domain = "apptest.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    (root / "index.js").write_text("console.log('x')")
    apps_ops.create_app(domain, root, "node", 8111, "index.js", go_version="")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.unit_name(domain)
    assert unit.exists()
    text = unit.read_text()
    assert "Environment=PORT=8111" in text
    assert "ExecStart=/usr/bin/env node index.js" in text
    assert "WorkingDirectory=" + str(root) in text


def test_unit_remove():
    domain = "apptest2.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    (root / "index.js").write_text("console.log('x')")
    apps_ops.create_app(domain, root, "node", 8112, "index.js")
    apps_ops.remove_app(domain, root, "node")
    assert not (Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.unit_name(domain)).exists()


def test_go_requires_binary():
    domain = "gotest.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    try:
        apps_ops.create_app(domain, root, "go", 8113, "app")
        raise AssertionError("harus error: binary tidak ada")
    except apps_ops.AppError as e:
        assert "Binary app tidak ada" in str(e)


def test_docker_requires_compose():
    domain = "docktest.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    try:
        apps_ops.create_app(domain, root, "docker", 8114, "")
        raise AssertionError("harus error: compose tidak ada")
    except apps_ops.AppError as e:
        assert "docker-compose.yml tidak ada" in str(e)


def test_docker_compose_file():
    domain = "dock2.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    (root / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx\n")
    apps_ops.create_app(domain, root, "docker", 8115, "")
    # fake docker (echo) sukses -> tidak error


def test_proxy_insert_remove():
    domain = "proxy.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = nginx_ops.vhost_path(domain)

    nginx_ops.proxy_insert(domain, "/app1", 9001)
    conf = vh.read_text()
    assert "location /app1 {" in conf
    assert "proxy_pass http://127.0.0.1:9001;" in conf
    assert conf.count("{") == conf.count("}"), "kurung tidak seimbang"

    # update port — block lama harus diganti, tidak dobel
    nginx_ops.proxy_insert(domain, "/app1", 9002)
    conf = vh.read_text()
    assert conf.count("location /app1") == 1
    assert "127.0.0.1:9002" in conf and "127.0.0.1:9001" not in conf

    nginx_ops.proxy_remove(domain, "/app1")
    conf = vh.read_text()
    assert "location /app1" not in conf
    assert conf.count("{") == conf.count("}"), "kurung tidak seimbang setelah hapus"


def test_proxy_full_domain():
    domain = "proxyfull.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = nginx_ops.vhost_path(domain)

    # proxy ON: listen port + location / proxy_pass
    nginx_ops.proxy_enable(domain, 9100)
    conf = vh.read_text()
    assert "listen 9100;" in conf
    assert "proxy_pass http://127.0.0.1:9100;" in conf
    assert "try_files" not in conf
    assert conf.count("{") == conf.count("}")

    # proxy OFF: balik static
    nginx_ops.proxy_disable(domain)
    conf = vh.read_text()
    assert "listen 80;" in conf
    assert "try_files $uri $uri/ =404;" in conf
    assert "proxy_pass" not in conf


def test_set_server_names():
    domain = "alias.example.com"
    webserver_ops.for_engine("nginx").create_site(domain)
    nginx_ops.set_server_names(domain, [domain, "www.alias.example.com", "alt.example.com"])
    conf = nginx_ops.vhost_path(domain).read_text()
    assert "server_name alias.example.com www.alias.example.com alt.example.com;" in conf
    # main tetap pertama
    nginx_ops.set_server_names(domain, ["x.example.com", domain])
    conf = nginx_ops.vhost_path(domain).read_text()
    assert "server_name alias.example.com x.example.com;" in conf
