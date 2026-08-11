"""Unit test App Store: katalog, deteksi, install/uninstall, fetch remote.
Jalankan:
    .venv/bin/python -m pytest test_appstore.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import appstore as store

def test_catalog_has_all_categories():
    cats = {i["category"] for i in store.CATALOG}
    assert cats == {"php", "node", "go", "app"}

def test_catalog_ids_unique():
    ids = [i["id"] for i in store.CATALOG]
    assert len(ids) == len(set(ids))

def test_detect_which_false_when_missing():
    assert store._detect({"type": "which", "bin": ["php9.9"]}) is False

def test_detect_dir_false_when_missing():
    assert store._detect({"type": "dir", "path": "/nonexistent/xyz"}) is False

def test_detect_unknown_type_false():
    assert store._detect({"type": "bogus"}) is False

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

def test_service_units_maps_php_and_apps():
    units = store.service_units()
    assert units.get("php8.4") == "php8.4-fpm"
    assert units.get("nginx") == "nginx"
    assert units.get("redis") == "redis-server"
    assert units.get("docker") == "docker"
    assert "node22" not in units  # node via nvm, bukan systemd

def test_docker_in_catalog():
    item = next(i for i in store.CATALOG if i["id"] == "docker")
    assert item["category"] == "app"
    assert item["service"] == "docker"
    assert item["install"][0] == store.APT

def test_webservers_in_catalog():
    ids = {i["id"] for i in store.CATALOG}
    assert {"nginx", "apache", "openlitespeed"} <= ids
    apache = next(i for i in store.CATALOG if i["id"] == "apache")
    assert apache["service"] == "apache2"
    ols = next(i for i in store.CATALOG if i["id"] == "openlitespeed")
    assert ols["service"] == "lsws"

def test_service_action_unknown_action_raises():
    try:
        store.service_action("php8.4", "bogus")
        assert False, "harus raise"
    except store.AppStoreError:
        pass

def test_service_action_unknown_item_raises():
    try:
        store.service_action("nope", "start")
        assert False, "harus raise"
    except store.AppStoreError:
        pass

def test_service_action_requires_installed():
    # php9.9 tidak ada di katalog → _find raise AppStoreError
    try:
        store.service_action("php7.4", "start")
        assert False, "harus raise"
    except store.AppStoreError:
        pass

def test_service_status_empty_without_service():
    assert store.service_status("node22") == ""

def test_list_catalog_has_service_field():
    items = store.list_catalog()
    assert all("service" in i for i in items)
    assert any(i["id"] == "nginx" and i["service"] == "nginx" for i in items)

def test_list_catalog_has_installed_flag():
    items = store.list_catalog()
    assert all("installed" in i for i in items)
    assert any(i["id"] == "php7.4" for i in items)

def test_validate_item_rejects_bad():
    assert store._validate_item({"id": "x"}) is False
    assert store._validate_item({"id": "x", "name": "X", "category": "app",
                                 "install": "notalist", "uninstall": [], "detect": {}}) is False

def test_parse_items_dedup_and_skip_invalid():
    data = {"items": [
        {"id": "a", "name": "A", "category": "app", "install": ["x"], "uninstall": ["y"], "detect": {"type": "which", "bin": ["a"]}},
        {"id": "a", "name": "A2", "category": "app", "install": ["x"], "uninstall": ["y"], "detect": {"type": "which", "bin": ["a"]}},
        {"id": "bad"},
    ]}
    items = store._parse_items(data)
    assert items is not None
    assert [i["id"] for i in items] == ["a"]

def test_load_catalog_uses_remote_cache():
    # tulis cache fresh → _load_catalog harus pakai cache, bukan statis
    cache_items = [{"id": "custom1", "name": "Custom", "category": "app",
                    "install": ["echo"], "uninstall": ["echo"], "detect": {"type": "which", "bin": ["zzz"]}}]
    store.APPSTORE_URL = "https://example.invalid/catalog.json"
    store._write_cache(cache_items)
    try:
        loaded = store._load_catalog()
        assert [i["id"] for i in loaded] == ["custom1"]
    finally:
        store.APPSTORE_URL = None
        if store.APPSTORE_CACHE.exists():
            store.APPSTORE_CACHE.unlink()