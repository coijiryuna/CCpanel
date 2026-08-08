"""Monitoring: statistik dashboard + status SSL per-site.

Data dikumpulkan read-only: jumlah site/db/ftp/user, total ukuran folder
site, umur site, status SSL (folder letsencrypt live ada atau tidak) +
expiry dari cert.pem. Tidak ada agent/daemon — dihitung per request.

Alerting (email/webhook) bukan bagian fitur ini — YAGNI sampai ada
kebutuhan eksplisit.
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import nginx

LETSENCRYPT_LIVE = Path(os.environ.get("CCPANEL_LETSENCRYPT_LIVE", "/etc/letsencrypt/live"))

def _folder_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

def _cert_expiry(domain: str) -> str | None:
    """Baca expiry cert.pem (format openssl). None kalau tak ada cert."""
    cert = LETSENCRYPT_LIVE / domain / "cert.pem"
    if not cert.is_file():
        return None
    res = subprocess.run(
        ["openssl", "x509", "-enddate", "-noout", "-in", str(cert)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        return None
    m = re.search(r"notAfter=(.+)", res.stdout)
    if not m:
        return None
    try:
        return datetime.datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").isoformat()
    except ValueError:
        return None

def _cpu_percent() -> float:
    """Persentase CPU saat ini via delta /proc/stat antar dua sampel."""
    def sample():
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        total = sum(int(x) for x in parts)
        idle = int(parts[3]) + int(parts[4])  # idle + iowait
        return total, idle
    t0, i0 = sample()
    time.sleep(0.1)
    t1, i1 = sample()
    dt, di = t1 - t0, i1 - i0
    return round(100 * (1 - di / dt), 1) if dt else 0.0

def _net_counters() -> dict:
    """Baca /proc/net/dev → {iface: {rx, tx}} cumulative bytes."""
    out = {}
    with open("/proc/net/dev") as f:
        next(f)  # header
        next(f)
        for line in f:
            iface, _, rest = line.partition(":")
            iface = iface.strip()
            fields = rest.split()
            out[iface] = {"rx": int(fields[0]), "tx": int(fields[8])}
    return out

def _net_traffic() -> dict:
    """Traffic per interface + total. Rate (B/s) via delta antar dua sampel."""
    a = _net_counters()
    time.sleep(0.1)
    b = _net_counters()
    dt = 0.1
    ifaces = {}
    for name in b:
        rx = b[name]["rx"] - a[name]["rx"]
        tx = b[name]["tx"] - a[name]["tx"]
        ifaces[name] = {
            "rx": b[name]["rx"], "tx": b[name]["tx"],  # cumulative
            "rx_rate": round(rx / dt), "tx_rate": round(tx / dt),  # B/s
        }
    return {
        "interfaces": ifaces,
        "total": {
            "rx": sum(i["rx"] for i in ifaces.values()),
            "tx": sum(i["tx"] for i in ifaces.values()),
            "rx_rate": sum(i["rx_rate"] for i in ifaces.values()),
            "tx_rate": sum(i["tx_rate"] for i in ifaces.values()),
        },
    }

def server_info() -> dict:
    """Info server: CPU, RAM, load, disk. Baca dari /proc — tanpa dependency."""
    # RAM: kB dari /proc/meminfo
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            mem[k] = int(v.split()[0]) * 1024

    root = shutil.disk_usage("/")

    # load average: /proc/loadavg (1, 5, 15 menit)
    with open("/proc/loadavg") as f:
        load1, load5, load15, *_ = f.read().split()

    uptime = datetime.timedelta(seconds=int(float(open("/proc/uptime").read().split()[0])))

    cores = os.cpu_count() or 0
    loads = [float(load1), float(load5), float(load15)]

    # model CPU + jumlah socket/physical core dari /proc/cpuinfo
    model = "Unknown"
    sockets = set()
    physical = set()
    cur_socket = None
    with open("/proc/cpuinfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "model name":
                model = v
            elif k == "physical id":
                cur_socket = v
                sockets.add(v)
            elif k == "core id":
                physical.add((cur_socket, v))  # core id unik per socket
    physical_cores = len(physical)

    return {
        "hostname": os.uname().nodename,
        "platform": f"{os.uname().sysname} {os.uname().release}",
        "uptime": str(uptime),
        "cpu": {
            "model": model,
            "sockets": len(sockets) or 1,
            "physical_cores": physical_cores or cores,
            "cores": cores,
            "load": {"onem": loads[0], "fivem": loads[1], "fivetenm": loads[2]},
            # persen kapasitas: load / cores * 100 (bisa >100 = overload)
            "load_percent": {"onem": round(loads[0] / cores * 100, 1),
                             "fivem": round(loads[1] / cores * 100, 1),
                             "fivetenm": round(loads[2] / cores * 100, 1)},
            "percent": _cpu_percent(),
        },
        "memory": {
            "total": mem.get("MemTotal", 0),
            "used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
            "available": mem.get("MemAvailable", 0),
            "swap_total": mem.get("SwapTotal", 0),
            "swap_used": mem.get("SwapTotal", 0) - mem.get("SwapFree", 0),
        },
        "disk": {
            "total": root.total,
            "used": root.used,
            "free": root.free,
        },
        "net": _net_traffic(),
    }

def dashboard(conn, owner_id: int | None = None) -> dict:
    """Hitung statistik panel. conn = koneksi DB aktif (pemanggil yang buka).
    owner_id=None → admin, lihat semua. owner_id set → client, hanya punyanya."""
    if owner_id is None:
        site_rows = conn.execute("SELECT * FROM sites").fetchall()
        db_count = conn.execute("SELECT COUNT(*) c FROM dbs").fetchone()["c"]
        ftp_count = conn.execute("SELECT COUNT(*) c FROM ftp_accounts").fetchone()["c"]
    else:
        site_rows = conn.execute(
            "SELECT * FROM sites WHERE owner_id = ?", (owner_id,)
        ).fetchall()
        db_count = conn.execute(
            "SELECT COUNT(*) c FROM dbs WHERE owner_id = ?", (owner_id,)
        ).fetchone()["c"]
        ftp_count = conn.execute(
            "SELECT COUNT(*) c FROM ftp_accounts f JOIN sites s ON s.id = f.site_id "
            "WHERE s.owner_id = ?", (owner_id,)
        ).fetchone()["c"]
    user_count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]

    total_size = 0
    sites = []
    for s in site_rows:
        root = Path(s["root_path"])
        size = _folder_size(root)
        total_size += size
        sites.append({
            "id": s["id"],
            "domain": s["domain"],
            "enabled": bool(s["enabled"]),
            "waf_enabled": bool(s["waf_enabled"]),
            "size": size,
            "ssl_expiry": _cert_expiry(s["domain"]),
            "created_at": s["created_at"],
        })
    sites.sort(key=lambda x: x["domain"].lower())

    return {
        "counts": {
            "sites": len(site_rows),
            "dbs": db_count,
            "ftp": ftp_count,
            "users": user_count,
        },
        "total_size": total_size,
        "sites": sites,
    }
