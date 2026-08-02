"""Unit test project standalone (tanpa domain) + vhost proxy domain nginx.
Jalankan:
    .venv/bin/python -m pytest test_projects.py
"""
import os
import sys
import tempfile
from pathlib import Path

# override env SEBELUM import core — path pakai env var saat import
_tmp = tempfile.mkdtemp(prefix="ccp-proj-test-")
os.environ["CCPANEL_SYSTEMD_DIR"] = str(Path(_tmp) / "systemd")
os.environ["CCPANEL_PROJECT_ROOT"] = str(Path(_tmp) / "project")
os.environ["CCPANEL_WWW_ROOT"] = str(Path(_tmp) / "www")
os.environ["CCPANEL_NGINX_CONF_DIR"] = str(Path(_tmp) / "conf")
os.environ["CCPANEL_TRASH_DIR"] = str(Path(_tmp) / "trash")
os.environ["CCPANEL_DOCKER_BIN"] = "echo"  # fake docker: echo selalu sukses

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import apps as apps_ops
from core import nginx as nginx_ops


def test_standalone_unit_node():
    root = apps_ops.create_standalone("api-gateway", "node", 8201, "index.js")
    assert root == apps_ops.project_root("api-gateway")
    assert root.is_dir()
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("api-gateway")
    assert unit.exists()
    text = unit.read_text()
    assert "Environment=PORT=8201" in text
    assert "ExecStart=/usr/bin/env node index.js" in text
    assert "WorkingDirectory=" + str(root) in text
    # unit site tidak boleh nyasar
    assert not (Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / "ccpanel-api-gateway.service").exists()


def test_standalone_name_validation():
    try:
        apps_ops.project_root("bad name/../x")
        raise AssertionError("harus error: nama tidak valid")
    except apps_ops.AppError as e:
        assert "hanya huruf/angka" in str(e)


def test_standalone_pm2_cmd():
    root = apps_ops.create_standalone("pm2-svc", "node", 8202, "app.js", pm2=True,
                                      run_opt="npm run prod", user="appuser")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("pm2-svc")
    text = unit.read_text()
    assert "User=appuser" in text
    assert "pm2 start " in text and "--name pm2-svc" in text and "npm run prod" in text


def test_standalone_node_version_path():
    root = apps_ops.create_standalone("nvm-svc", "node", 8205, "index.js",
                                      node_version="v22")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("nvm-svc")
    text = unit.read_text()
    assert "export PATH=$HOME/.nvm/versions/node/v22/bin:$PATH && /usr/bin/env node index.js" in text


def test_standalone_python_bind_localhost():
    root = apps_ops.create_standalone("py-api", "python", 8203, "app:app")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("py-api")
    text = unit.read_text()
    assert "gunicorn app:app --bind 127.0.0.1:8203" in text


def test_standalone_remove():
    apps_ops.create_standalone("to-remove", "node", 8204, "index.js")
    apps_ops.remove_standalone("to-remove", "node")
    assert not (Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("to-remove")).exists()


def test_standalone_status_pid():
    # systemctl asli tidak ada di env test — status harus tidak crash
    st = apps_ops.standalone_status("missing-proj", "node")
    assert "state" in st and "pid" in st


def test_project_vhost_proxy():
    domain = "api.backend.dev"
    nginx_ops.project_proxy_enable(domain, 8301)
    vh = nginx_ops.project_vhost_path(domain)
    assert vh.exists()
    conf = vh.read_text()
    assert f"server_name {domain};" in conf
    assert "listen 80;" in conf
    assert "proxy_pass http://127.0.0.1:8301;" in conf
    assert "root " not in conf  # project tidak punya docroot
    assert conf.count("{") == conf.count("}")

    # idempotent: hapus dua kali tidak error
    nginx_ops.project_proxy_disable(domain)
    assert not vh.exists()
    nginx_ops.project_proxy_disable(domain)


def test_project_vhost_duplicate_rejected():
    domain = "dup.backend.dev"
    nginx_ops.project_proxy_enable(domain, 8302)
    try:
        nginx_ops.project_proxy_enable(domain, 8303)
        raise AssertionError("harus error: vhost sudah ada")
    except nginx_ops.NginxError as e:
        assert "sudah ada" in str(e)
    nginx_ops.project_proxy_disable(domain)


def test_project_vhost_invalid_domain():
    try:
        nginx_ops.project_proxy_enable("not a domain", 8304)
        raise AssertionError("harus error: domain tidak valid")
    except nginx_ops.NginxError as e:
        assert "tidak valid" in str(e)
