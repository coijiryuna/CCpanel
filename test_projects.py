"""Unit test project standalone (tanpa domain) + vhost proxy domain nginx.
Jalankan:
    .venv/bin/python -m pytest test_projects.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import apps as apps_ops
from core import nginx as nginx_ops


def test_standalone_unit_node():
    root = apps_ops.create_standalone("api-gateway", "node", 8201, "index.js", go_version="")
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
    root = apps_ops.create_standalone("pm2-svc", "node", 8202, "app.js", pm2=True, go_version="",
                                      run_opt="npm run prod", user="appuser")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("pm2-svc")
    text = unit.read_text()
    assert "User=appuser" in text
    assert "pm2 start " in text and "--name pm2-svc" in text and "npm run prod" in text


def test_standalone_node_version_path():
    root = apps_ops.create_standalone("nvm-svc", "node", 8205, "index.js", go_version="",
                                      node_version="v22")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("nvm-svc")
    text = unit.read_text()
    assert "export PATH=$HOME/.nvm/versions/node/v22/bin:$PATH && /usr/bin/env node index.js" in text


def test_standalone_python_bind_localhost():
    root = apps_ops.create_standalone("py-api", "python", 8203, "app:app", go_version="")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("py-api")
    text = unit.read_text()
    assert "gunicorn app:app --bind 127.0.0.1:8203" in text


def test_standalone_remove():
    apps_ops.create_standalone("to-remove", "node", 8204, "index.js", go_version="")
    apps_ops.remove_standalone("to-remove", "node")
    assert not (Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("to-remove")).exists()


def test_standalone_status_pid():
    # systemctl asli tidak ada di env test — status harus tidak crash
    st = apps_ops.standalone_status("missing-proj", "node")
    assert "state" in st and "pid" in st

# ----------------------------------------------------------------- auto deps

def _write_project_files(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")

def test_resolve_entry_node_package_main(monkeypatch):
    root = apps_ops.project_root("detect-main")
    _write_project_files(root, {"package.json": '{"name":"x","main":"src/server.js","scripts":{"start":"node src/server.js"}}'})
    assert apps_ops.resolve_entry("node", root, "") == "src/server.js"
    assert apps_ops.resolve_entry("node", root, "auto") == "src/server.js"

def test_resolve_entry_node_scripts_start(monkeypatch):
    root = apps_ops.project_root("detect-start")
    _write_project_files(root, {"package.json": '{"name":"x","scripts":{"start":"node app.js"}}'})
    assert apps_ops.resolve_entry("node", root, "") == "app.js"

def test_resolve_entry_python(monkeypatch):
    root = apps_ops.project_root("detect-py")
    _write_project_files(root, {"app.py": "print(1)"})
    assert apps_ops.resolve_entry("python", root, "") == "app:app"
    root2 = apps_ops.project_root("detect-py2")
    _write_project_files(root2, {"main.py": "print(1)"})
    assert apps_ops.resolve_entry("python", root2, "") == "main:app"

def test_install_deps_node_uses_npm_ci_when_lock(monkeypatch):
    root = apps_ops.project_root("auto-npm-ci")
    _write_project_files(root, {
        "package.json": '{"name":"x","dependencies":{"express":"^4"}}',
        "package-lock.json": "{}",
    })
    calls: list[list[str]] = []
    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return apps_ops.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(apps_ops, "_run_in", fake_run)
    apps_ops._install_deps("node", root, "www")
    assert any("npm ci" in " ".join(c) for c in calls)
    # lock tidak ada -> npm install
    root2 = apps_ops.project_root("auto-npm-install")
    _write_project_files(root2, {"package.json": '{"name":"x","dependencies":{"express":"^4"}}'})
    calls.clear()
    apps_ops._install_deps("node", root2, "www")
    assert any("npm install" in " ".join(c) for c in calls)

def test_install_deps_node_skips_when_node_modules(monkeypatch):
    root = apps_ops.project_root("auto-npm-skip")
    _write_project_files(root, {"package.json": '{"name":"x","dependencies":{"express":"^4"}}'})
    (root / "node_modules").mkdir()
    calls: list[list[str]] = []
    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return apps_ops.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(apps_ops, "_run_in", fake_run)
    apps_ops._install_deps("node", root, "www")
    assert calls == []

def test_install_deps_go_builds_binary(monkeypatch):
    root = apps_ops.project_root("auto-go")
    _write_project_files(root, {"go.mod": "module x\n"})
    calls: list[list[str]] = []
    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return apps_ops.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(apps_ops, "_run_in", fake_run)
    apps_ops._install_deps("go", root, "www")
    assert calls and calls[-1][:3] == ["go", "build", "-o"]
    assert calls[-1][3] == "auto-go"

def test_install_deps_python_requirements(monkeypatch):
    root = apps_ops.project_root("auto-py")
    _write_project_files(root, {"requirements.txt": "requests\n"})
    calls: list[list[str]] = []
    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return apps_ops.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(apps_ops, "_run_in", fake_run)
    apps_ops._install_deps("python", root, "www")
    assert calls and calls[0][:2] == ["pip", "install"]

def test_install_deps_empty_dir_skips(monkeypatch):
    root = apps_ops.project_root("auto-empty")
    root.mkdir(parents=True, exist_ok=True)
    calls: list[list[str]] = []
    def fake_run(cmd, cwd=None, timeout=600):
        calls.append(cmd)
        return apps_ops.subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(apps_ops, "_run_in", fake_run)
    apps_ops._install_deps("node", root, "www")
    assert calls == []

# ----------------------------------------------------------------- unit cmd

def _fake_systemctl_success(monkeypatch):
    def fake(cmd, cwd=None, timeout=600):
        return apps_ops.subprocess.CompletedProcess(["systemctl", *cmd], 0, "", "")
    monkeypatch.setattr(apps_ops, "systemctl", fake)

def test_standalone_node_npm_start_cmd(monkeypatch):
    _fake_systemctl_success(monkeypatch)
    root = apps_ops.project_root("npm-start-app")
    _write_project_files(root, {"package.json": '{"name":"x","scripts":{"start":"node server.js"}}'})
    apps_ops.create_standalone("npm-start-app", "node", 8210, "", go_version="")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("npm-start-app")
    text = unit.read_text()
    assert "ExecStart=/usr/bin/env npm start" in text

def test_standalone_go_binary_cmd(monkeypatch):
    _fake_systemctl_success(monkeypatch)
    root = apps_ops.project_root("go-bin-app")
    _write_project_files(root, {
        "go.mod": "module gobinapp\n\ngo 1.21\n",
        "main.go": "package main\n\nimport \"fmt\"\n\nfunc main() { fmt.Println(\"hi\") }\n",
    })
    apps_ops.create_standalone("go-bin-app", "go", 8211, "auto", go_version="")
    unit = Path(os.environ["CCPANEL_SYSTEMD_DIR"]) / apps_ops.standalone_unit_name("go-bin-app")
    text = unit.read_text()
    assert f"ExecStart=/usr/bin/env ./go-bin-app" in text
    # binary hasil build harus ada
    assert (root / "go-bin-app").exists()


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
