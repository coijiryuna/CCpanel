"""Unit test App Store: katalog, deteksi, install/uninstall.
Jalankan:
    .venv/bin/python -m pytest test_appstore.py
"""
import os
import sys
import tempfile
from pathlib import Path

# override env SEBELUM import core
_tmp = tempfile.mkdtemp(prefix="ccp-appstore-test-")
os.environ["CCPANEL_APT"] = "echo"  # fake apt: echo selalu sukses
os.environ["CCPANEL_NVM_DIR"] = str(Path(_tmp) / "nvm")
os.environ["CCPANEL_GO_ROOT"] = str(Path(_tmp) / "go")
os.environ["CCPANEL_APPSTORE_LOG"] = str(Path(_tmp) / "appstore.log")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import appstore as store

def test_catalog_has_all_categories():
    cats = {i["category"] for i in store.CATALOG}
    assert cats == {"php", "node", "go", "app"}

def test_catalog_ids_unique():
    ids = [i["id"] for i in store.CATALOG]
    assert len(ids) == len(set(ids))

def test_php_detect_false_when_missing():
    assert store._php_detect("9.9") is False

def test_node_detect_false_when_missing():
    assert store._node_detect("v99") is False

def test_go_detect_false_when_missing():
    assert store._go_detect("9.9") is False

def test_install_php_ok():
    res = store.install("php7.4")
    assert res["ok"] is True
    assert res["id"] == "php7.4"

def test_install_unknown_raises():
    try:
        store.install("nope")
        assert False, "harus raise"
    except store.AppStoreError:
        pass

def test_list_catalog_has_installed_flag():
    items = store.list_catalog()
    assert all("installed" in i for i in items)
    assert any(i["id"] == "php7.4" for i in items)