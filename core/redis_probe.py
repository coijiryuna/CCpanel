"""Redis live overview: db0..db15 + sample keys. Pakai lib `redis` (opsional).

Kalau lib/server tak ada → available=False, UI tampil pesan. Struktur db0-db15
tetap dirender frontend; isi hanya kalau server hidup.
"""
from __future__ import annotations

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None

DEFAULT_DBS = 16  # redis default databases=16
KEY_LIMIT = 200   # maks key per db (hindari payload gede)


def _conn(db: int, host: str = "localhost", port: int = 6379):
    return redis_lib.Redis(host=host, port=port, db=db, socket_connect_timeout=2)


def _dec(b):
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else b


def _fmt_value(r, key: str, t: str) -> tuple[str, int]:
    """Value preview + length untuk satu key. Return (display, length)."""
    try:
        if t == "string":
            v = r.get(key)
            if v is None:
                return "", 0
            return _dec(v), len(v)
        if t == "list":
            n = r.llen(key)
            items = [_dec(i) for i in r.lrange(key, 0, 9)]
            return ", ".join(items) + ("..." if n > 10 else ""), n
        if t == "hash":
            raw = r.hgetall(key)
            n = len(raw)
            pairs = ", ".join(f"{_dec(k)}={_dec(v)}" for k, v in list(raw.items())[:10])
            return pairs + ("..." if n > 10 else ""), n
        if t == "set":
            n = r.scard(key)
            items = [_dec(i) for i in list(r.smembers(key))[:10]]
            return ", ".join(items) + ("..." if n > 10 else ""), n
        if t == "zset":
            n = r.zcard(key)
            items = [_dec(m) for m, _ in r.zrange(key, 0, 9, withscores=True)]
            return ", ".join(items) + ("..." if n > 10 else ""), n
    except Exception as e:  # key bisa expired antara type & read
        return f"err: {e}", 0
    return "", 0


def _inspect(r, key: bytes) -> dict:
    """Ambil tipe + value + length + TTL untuk satu key."""
    k = _dec(key)
    t = _dec(r.type(key))
    value, length = _fmt_value(r, k, t)
    ttl = r.ttl(key)  # -1 persist, -2 tidak ada
    return {"key": k, "type": t, "value": value, "length": length, "ttl": ttl}


def overview(host: str = "localhost", port: int = 6379) -> dict:
    """List db0..db15 dengan key count + sample keys. available=False kalau gagal."""
    if redis_lib is None:
        return {"available": False, "error": "lib redis tidak terinstall", "dbs": []}

    dbs = []
    for idx in range(DEFAULT_DBS):
        db = {"index": idx, "keys": 0, "samples": []}
        try:
            r = _conn(idx, host, port)
            dbs.append(db)  # simpan dulu; isi kalau connect
            info = r.info("keyspace")
            db["keys"] = int(info.get(f"db{idx}", {}).get("keys", 0))
            if db["keys"]:
                keys = list(r.scan_iter(count=100))[:KEY_LIMIT] or []
                db["samples"] = [_inspect(r, k) for k in keys]
        except Exception as e:
            db["error"] = str(e)
            db["keys"] = 0
    # available hanya kalau minimal 1 db connect sukses
    ok = [d for d in dbs if "error" not in d]
    return {"available": bool(ok), "error": "" if ok else "redis server tidak bisa dihubungi", "dbs": dbs}


def set_key(db: int, key: str, value: str, ttl: int = -1, host: str = "localhost", port: int = 6379) -> dict:
    """Simpan/update key. ttl>=0 = detik expire; -1 = persist (hapus expire)."""
    if redis_lib is None:
        return {"ok": False, "error": "lib redis tidak terinstall"}
    r = _conn(db, host, port)
    r.set(key, value)
    if ttl >= 0:
        r.expire(key, ttl)
    else:
        r.persist(key)
    return {"ok": True}


def delete_key(db: int, key: str, host: str = "localhost", port: int = 6379) -> dict:
    """Hapus satu key. Return ok=False kalau key tak ada."""
    if redis_lib is None:
        return {"ok": False, "error": "lib redis tidak terinstall"}
    r = _conn(db, host, port)
    n = r.delete(key)
    return {"ok": bool(n), "deleted": n}
