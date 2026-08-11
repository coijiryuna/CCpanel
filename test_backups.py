"""Test core/backup: penamaan unik file backup (regression fix)."""
import tempfile
from pathlib import Path

from core.backup import _unique_path


def test_unique_path_keeps_compound_suffix():
    """Timestamp harus disisipkan SEBELUM .tar.gz/.sql.gz — bukan setelahnya."""
    d = Path(tempfile.mkdtemp())
    p = d / "site.com.tar.gz"
    p.touch()
    r = _unique_path(p)
    assert r.name.endswith(".tar.gz")
    assert r.name != p.name
    assert "site.com.tar." not in r.name  # pola lama: site.com.tar.<stamp>.gz


def test_unique_path_dedup_same_second():
    """Dua backup dalam detik sama → nama tetap unik (-1, -2, dst)."""
    d = Path(tempfile.mkdtemp())
    p = d / "db.sql.gz"
    p.touch()
    r1 = _unique_path(p)
    r1.touch()
    r2 = _unique_path(p)
    assert r1 != r2
    assert r1.suffixes[-2:] == [".sql", ".gz"]
    assert r2.suffixes[-2:] == [".sql", ".gz"]


def test_unique_path_plain_suffix_unchanged():
    """File biasa tetap dapat stamp sebelum suffix tunggal."""
    d = Path(tempfile.mkdtemp())
    p = d / "note.txt"
    p.touch()
    r = _unique_path(p)
    assert r.name.endswith(".txt")
    assert ".txt." not in r.name
