"""Test core/cms: katalog + deteksi CMS."""
import tempfile
from pathlib import Path

from core.cms import CMS_CATALOG, CmsError, _extract, _write_wp_config, catalog, detect

def test_catalog_lists_known_cms():
    ids = {c["id"] for c in catalog()}
    assert {"wordpress", "joomla", "drupal"} <= ids

def test_extract_moves_subdir_to_dest():
    """Arsip tar.gz berisi wordpress/ → isinya pindah ke dest langsung."""
    import tarfile

    d = Path(tempfile.mkdtemp())
    src = d / "wordpress"
    src.mkdir()
    (src / "index.php").write_text("<?php // wp")
    (src / ".htaccess").write_text("# deny")
    archive = d / "wp.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        t.add(src, arcname="wordpress")
    dest = d / "root"
    dest.mkdir()
    _extract(archive, dest, "tar.gz", "wordpress")
    assert (dest / "index.php").exists()
    assert (dest / ".htaccess").exists()  # file dot ikut pindah
    assert not (dest / "wordpress").exists()

def test_extract_rejects_missing_subdir():
    import tarfile

    d = Path(tempfile.mkdtemp())
    archive = d / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        # isi arsip: file di root (tanpa subdir wordpress)
        info = tarfile.TarInfo("readme.txt")
        info.size = 3
        t.addfile(info, __import__("io").BytesIO(b"abc"))
    dest = d / "root"
    dest.mkdir()
    try:
        _extract(archive, dest, "tar.gz", "wordpress")
        assert False, "harus error"
    except CmsError:
        pass

def test_write_wp_config_replaces_placeholders():
    d = Path(tempfile.mkdtemp())
    sample = d / "wp-config-sample.php"
    sample.write_text(
        "define('DB_NAME', 'database_name_here');\n"
        "define('DB_USER', 'username_here');\n"
        "define('DB_PASSWORD', 'password_here');\n"
        "define('DB_HOST', 'localhost');\n"
        "define('AUTH_KEY', 'put your unique phrase here');\n"
        "define('SECURE_AUTH_KEY', 'put your unique phrase here');\n"
    )
    _write_wp_config(d, "my_db", "my_user", "my_pass")
    out = (d / "wp-config.php").read_text()
    assert "my_db" in out and "my_user" in out and "my_pass" in out
    assert "127.0.0.1" in out
    assert "put your unique phrase here" not in out
    assert "database_name_here" not in out
    assert not sample.exists()

def test_detect_known_cms():
    d = Path(tempfile.mkdtemp())
    (d / "wp-config.php").write_text("x")
    assert detect(d) == "wordpress"
    (d / "wp-config.php").unlink()
    (d / "configuration.php").write_text("x")
    assert detect(d) == "joomla"
    (d / "configuration.php").unlink()
    (d / "core").mkdir()
    (d / "core" / "lib").mkdir()
    (d / "core" / "lib" / "Drupal.php").write_text("x")
    assert detect(d) == "drupal"

def test_install_rejects_unknown_cms(monkeypatch):
    from core.cms import install

    d = Path(tempfile.mkdtemp())
    root = d / "site.com"
    root.mkdir()
    # monkeypatch nginx.root_path agar tidak butuh setup webserver nyata
    import core.cms as cms_mod
    monkeypatch.setattr(cms_mod.nginx, "root_path", lambda domain: root)
    try:
        install("nope", "site.com", "db", "u", "p")
        assert False, "harus error"
    except CmsError as e:
        assert "tidak dikenal" in str(e)
