"""Installer CMS: WordPress + lainnya.

Download arsip resmi (tar.gz/zip) dari URL katalog, extract ke folder root
site, tulis file konfigurasi (wp-config.php), dan setup database (buat DB +
user + import skema kalau disertakan). Semua via subprocess argumen-list.

Katalog CMS (id → info). install: list argumen. Semua URL resmi (wordpress.org
pakai versi terbaru via latest.tar.gz).
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from . import database, nginx, validate

CMS_CATALOG: dict[str, dict] = {
    "wordpress": {
        "name": "WordPress",
        "desc": "CMS paling populer (blog, company profile, toko)",
        "url": "https://wordpress.org/latest.tar.gz",
        "type": "tar.gz",
        "needs_db": True,
        "config_template": "wp-config",
        "db_engine": "mysql",
        "languages": {
            "id_ID": "https://id.wordpress.org/latest-id_ID.tar.gz",
            "en_US": None,  # default arsip
        },
    },
    "joomla": {
        "name": "Joomla",
        "desc": "CMS + framework, cocok portal berita",
        "url": "https://downloads.joomla.org/cms/joomla5/5-2-4/Joomla_5.2.4-Stable-Full_Package.tar.gz",
        "type": "tar.gz",
        "needs_db": True,
        "config_template": None,  # instalasi lewat web wizard
        "db_engine": "mysql",
        "languages": {},
    },
    "drupal": {
        "name": "Drupal",
        "desc": "CMS enterprise, fleksibel & aman",
        "url": "https://ftp.drupal.org/files/projects/drupal-11.1.0.tar.gz",
        "type": "tar.gz",
        "needs_db": True,
        "config_template": None,  # instalasi lewat web wizard
        "db_engine": "mysql",
        "languages": {},
    },
}

# Versi WordPress: versi → URL arsip (latest = rilis terbaru)
WP_VERSIONS: dict[str, str] = {
    "latest": "https://wordpress.org/latest.tar.gz",
    "6.7": "https://wordpress.org/wordpress-6.7.tar.gz",
    "6.6": "https://wordpress.org/wordpress-6.6.tar.gz",
    "6.5": "https://wordpress.org/wordpress-6.5.tar.gz",
}

# subdir dalam arsip yang berisi file CMS (wordpress/ → pindah ke root)
_ARCHIVE_ROOT_DIR: dict[str, str] = {
    "wordpress": "wordpress",
    "drupal": "drupal-11.1.0",
}

class CmsError(Exception):
    pass

def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

def catalog() -> list[dict]:
    out = []
    for cid, meta in CMS_CATALOG.items():
        item = {"id": cid, **meta}
        # versi & bahasa per CMS
        if cid == "wordpress":
            item["versions"] = list(WP_VERSIONS.keys())
        out.append(item)
    return out

def _download(url: str, dest: Path) -> None:
    try:
        with urllib.request.urlopen(url, timeout=120) as r, dest.open("wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        raise CmsError(f"Download gagal: {e}") from e

def _extract(archive: Path, dest: Path, cms_type: str, subdir: str | None) -> None:
    """Extract arsip ke dest. Kalau isi cuma 1 subdir (mis. wordpress/),
    pindahkan isinya ke dest langsung."""
    tmp = dest.parent / f".{dest.name}-extract"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        if cms_type == "zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="data")
        src = tmp / subdir if subdir else tmp
        if not src.is_dir():
            raise CmsError(f"Arsip tidak berisi folder {subdir or '(root)'}")
        # pindahkan isi (termasuk file dot: .htaccess, .user.ini)
        for item in src.iterdir():
            shutil.move(str(item), str(dest / item.name))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _wp_config_set_lang(text: str, lang: str | None) -> str:
    """Sisipkan WPLANG di wp-config. Default en_US (tanpa baris)."""
    if not lang or lang == "en_US":
        return text
    return text.replace(
        "define( 'WP_DEBUG', false );",
        "define( 'WP_DEBUG', false );\n"
        f"define( 'WPLANG', '{lang}' );",
        1,
    )

def _write_wp_config(root: Path, db_name: str, db_user: str, db_pass: str,
                     lang: str | None = None) -> None:
    """Tulis wp-config.php dari template resmi WordPress + salt acak + bahasa."""
    sample = root / "wp-config-sample.php"
    if not sample.exists():
        raise CmsError("wp-config-sample.php tidak ada di arsip WordPress")
    text = sample.read_text()
    text = text.replace("database_name_here", db_name)
    text = text.replace("username_here", db_user)
    text = text.replace("password_here", db_pass)
    text = text.replace("localhost", "127.0.0.1")
    # ganti semua placeholder salt jadi nilai acak
    salt = secrets.token_hex(32)
    text = text.replace("put your unique phrase here", salt)
    text = _wp_config_set_lang(text, lang)
    (root / "wp-config.php").write_text(text)
    (root / "wp-config-sample.php").unlink(missing_ok=True)

def _wp_version(root: Path) -> str | None:
    """Baca versi WordPress dari wp-includes/version.php."""
    f = root / "wp-includes" / "version.php"
    if not f.exists():
        return None
    m = re.search(r"wp_version\s*=\s*'([^']+)'", f.read_text())
    return m.group(1) if m else None

def install(cms_id: str, domain: str, db_name: str, db_user: str, db_pass: str,
            php_version: str = "static", lang: str | None = None,
            wp_version: str = "latest") -> dict:
    """Install CMS ke root site. Buat DB + user mysql (kalau needs_db)."""
    meta = CMS_CATALOG.get(cms_id)
    if meta is None:
        raise CmsError(f"CMS tidak dikenal: {cms_id}. Pilihan: {', '.join(CMS_CATALOG)}")
    if not validate.valid_domain(domain):
        raise CmsError("Domain tidak valid")
    root = nginx.root_path(domain)
    if not root.is_dir():
        raise CmsError(f"Folder root site tidak ada: {root} — buat site dulu")
    if (root / "index.php").exists() or (root / "wp-config.php").exists():
        raise CmsError("Folder root sudah berisi CMS — kosongkan dulu")

    # pilih URL arsip: versi + bahasa (khusus WordPress)
    url = meta["url"]
    if cms_id == "wordpress":
        if wp_version and wp_version in WP_VERSIONS:
            url = WP_VERSIONS[wp_version]
        if lang and lang in meta.get("languages", {}) and meta["languages"][lang]:
            url = meta["languages"][lang]

    # download + extract
    archive = root.parent / f".{domain}-{cms_id}.download"
    try:
        _download(url, archive)
        _extract(archive, root, meta["type"], _ARCHIVE_ROOT_DIR.get(cms_id))
    except CmsError:
        raise
    except Exception as e:
        raise CmsError(f"Install gagal: {e}") from e
    finally:
        archive.unlink(missing_ok=True)

    # setup DB
    db_created = None
    if meta.get("needs_db"):
        try:
            database.for_engine(meta["db_engine"]).create_db(db_name, db_user, db_pass, "localhost")
            db_created = (db_name, db_user, db_pass)
        except database.DatabaseError as e:
            # rollback file CMS, biar install ulang bersih
            shutil.rmtree(root, ignore_errors=True)
            raise CmsError(f"Buat database gagal: {e}") from e

    # config file
    try:
        if meta.get("config_template") == "wp-config":
            _write_wp_config(root, db_name, db_user, db_pass, lang=lang)
    except CmsError as e:
        if db_created:
            try:
                database.for_engine(meta["db_engine"]).drop_db(db_created[0], db_created[1], "localhost")
            except Exception:
                pass
        shutil.rmtree(root, ignore_errors=True)
        raise

    # PHP-FPM pool + block vhost (kalau pakai PHP)
    if cms_id == "wordpress" and php_version != "static":
        try:
            from . import php as php_ops
            php_ops.create_pool(domain, php_version)
            php_ops.insert_php_block(domain, php_version, None, None)
        except php_ops.PhpError as e:
            if db_created:
                try:
                    database.for_engine(meta["db_engine"]).drop_db(db_created[0], db_created[1], "localhost")
                except Exception:
                    pass
            shutil.rmtree(root, ignore_errors=True)
            raise CmsError(f"Setup PHP gagal: {e}") from e

    version = _wp_version(root) if cms_id == "wordpress" else None
    return {
        "ok": True, "cms": cms_id, "domain": domain, "db": db_name,
        "php_version": php_version, "lang": lang or "en_US",
        "version": version,
    }

def detect(root: Path) -> str | None:
    """Deteksi CMS terpasang dari isi folder root."""
    if (root / "wp-config.php").exists():
        return "wordpress"
    if (root / "configuration.php").exists():
        return "joomla"
    if (root / "core" / "lib" / "Drupal.php").exists() or (root / "web.config").exists():
        return "drupal"
    return None
