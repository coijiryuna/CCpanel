"""Unit test PHP-FPM pool + vhost fastcgi block. Jalankan:
    .venv/bin/python -m pytest test_php.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import php as php_ops
from core import webserver as webserver_ops

def test_pool_create_remove():
    domain = "phptest.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    pool = php_ops.create_pool(domain, "php8.1")
    assert pool.exists()
    assert "php8.1-fpm-phptest.example.com.sock" in pool.read_text()
    php_ops.remove_pool(domain, "php8.1")
    assert not pool.exists()

def test_set_php_version_vhost_block():
    domain = "phpvhost.example.com"
    # buat site via nginx engine — bikin folder root + vhost
    webserver_ops.for_engine("nginx").create_site(domain)
    vh = webserver_ops.for_engine("nginx").vhost_path(domain)

    php_ops.set_php_version(domain, "static", "php8.2", vh)
    assert "BEGIN CCPANEL PHP" in vh.read_text()
    assert "php8.2-fpm-phpvhost.example.com.sock" in vh.read_text()

    # pindah ke versi lain — block lama harus ganti
    php_ops.set_php_version(domain, "php8.2", "php8.3", vh)
    text = vh.read_text()
    assert "php8.3-fpm-phpvhost.example.com.sock" in text
    assert "php8.2-fpm-phpvhost.example.com.sock" not in text

    # kembali ke static — block harus hilang
    php_ops.set_php_version(domain, "php8.3", "static", vh)
    assert "BEGIN CCPANEL PHP" not in vh.read_text()

def test_invalid_version_rejected():
    domain = "bad.example.com"
    root = webserver_ops.root_path(domain)
    root.mkdir(parents=True)
    try:
        php_ops.create_pool(domain, "php5.6")
    except php_ops.PhpError:
        return
    raise AssertionError("php5.6 harus ditolak")
