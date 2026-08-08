"""Unit test cron custom (crontab di-mock, tanpa root). Jalankan:
    .venv/bin/python -m pytest test_cron.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import cron as cron_ops

class FakeCrontab:
    """Simulasi crontab user: isi disimpan di list, perintah dipanggil dicatat."""
    def __init__(self):
        self.content = ""  # isi crontab saat ini
        self.calls = []

    def __call__(self, args, input=None):
        self.calls.append((args, input))
        if args == ["-l"]:
            if self.content == "":
                # crontab -l exit 1 + pesan "no crontab" saat kosong
                return cron_ops.subprocess.CompletedProcess(["crontab", "-l"], 1, "", "no crontab for user")
            return cron_ops.subprocess.CompletedProcess(["crontab", "-l"], 0, self.content, "")
        if args == ["-"]:
            self.content = input or ""
            return cron_ops.subprocess.CompletedProcess(["crontab", "-"], 0, "", "")
        raise AssertionError(f"argumen crontab tak dikenal: {args}")

def test_sync_custom_writes_lines(monkeypatch):
    fake = FakeCrontab()
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    res = cron_ops.sync_custom([
        {"id": 1, "kind": "command", "schedule": "0 3 * * *", "command": "/bin/backup.sh"},
        {"id": 2, "kind": "command", "schedule": "*/5 * * * *", "command": "/usr/bin/healthcheck"},
    ])
    assert res["count"] == 2
    assert "0 3 * * * /bin/backup.sh  # ccpanel-custom-1" in fake.content
    assert "*/5 * * * * /usr/bin/healthcheck  # ccpanel-custom-2" in fake.content

def test_sync_custom_url_and_script(monkeypatch):
    fake = FakeCrontab()
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    cron_ops.sync_custom([
        {"id": 4, "kind": "url", "schedule": "*/5 * * * *", "command": "https://api.example.com/hook?x=1"},
        {"id": 5, "kind": "script", "schedule": "0 2 * * *", "command": "/www/project/cron.sh"},
    ])
    assert "curl -fsS --max-time 60 'https://api.example.com/hook?x=1'  # ccpanel-custom-4" in fake.content
    assert "bash /www/project/cron.sh  # ccpanel-custom-5" in fake.content

def test_sync_custom_preserves_other_lines(monkeypatch):
    fake = FakeCrontab()
    fake.content = "0 4 * * * /usr/bin/other  # ccpanel-ssl-renew\n"
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    cron_ops.sync_custom([{"id": 9, "kind": "command", "schedule": "1 2 3 4 5", "command": "cmd"}])
    assert "ccpanel-ssl-renew" in fake.content
    assert "ccpanel-custom-9" in fake.content

def test_sync_custom_removes_stale(monkeypatch):
    fake = FakeCrontab()
    fake.content = "0 3 * * * /old.sh  # ccpanel-custom-5\n"
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    # job 5 sudah dihapus dari DB, sync dengan list kosong -> line harus hilang
    cron_ops.sync_custom([])
    assert "ccpanel-custom-5" not in fake.content
    assert fake.content == ""

def test_remove_custom(monkeypatch):
    fake = FakeCrontab()
    fake.content = "0 3 * * * /a.sh  # ccpanel-custom-7\n0 4 * * * /b.sh  # ccpanel-ssl-renew\n"
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    cron_ops.remove_custom(7)
    assert "ccpanel-custom-7" not in fake.content
    assert "ccpanel-ssl-renew" in fake.content

def test_list_custom(monkeypatch):
    fake = FakeCrontab()
    fake.content = (
        "0 3 * * * /a.sh  # ccpanel-custom-1\n"
        "*/10 * * * * /usr/bin/check --fast  # ccpanel-custom-2\n"
        "0 4 * * * /b.sh  # ccpanel-ssl-renew\n"
    )
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    jobs = cron_ops.list_custom()
    assert len(jobs) == 2
    assert jobs[0] == {"id": 1, "schedule": "0 3 * * *", "command": "/a.sh"}
    assert jobs[1]["id"] == 2
    assert jobs[1]["command"] == "/usr/bin/check --fast"

def test_custom_line_roundtrip(monkeypatch):
    fake = FakeCrontab()
    monkeypatch.setattr(cron_ops, "_crontab", fake)
    cron_ops.sync_custom([{"id": 3, "kind": "command", "schedule": "30 4 1,15 * *", "command": "echo hi > /tmp/x"}])
    jobs = cron_ops.list_custom()
    assert jobs == [{"id": 3, "schedule": "30 4 1,15 * *", "command": "echo hi > /tmp/x"}]
