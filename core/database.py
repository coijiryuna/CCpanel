"""Dispatcher database engine: mysql (default) / postgresql / mongodb / redis.

server.py hanya bicara ke modul ini — pilih engine aktif dari env
CCPANEL_DATABASE (default mysql). Interface umum:
  create_db / reset_password / drop_db / test
Per-DB engine disimpan kolom `db_type` di tabel `dbs` — operasi dispatch ke engine yang benar.
"""
from __future__ import annotations

import os

from . import mysql, postgresql

class MongoStub:
    @staticmethod
    def create_db(name, user, pw, host):
        raise DatabaseError("MongoDB NoSQL tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def reset_password(user, pw, host):
        raise DatabaseError("MongoDB NoSQL tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def drop_db(name, user, host):
        raise DatabaseError("MongoDB NoSQL tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def test():
        raise DatabaseError("MongoDB NoSQL tidak didukung.")

class RedisStub:
    @staticmethod
    def create_db(name, user, pw, host):
        raise DatabaseError("Redis in-memory tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def reset_password(user, pw, host):
        raise DatabaseError("Redis in-memory tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def drop_db(name, user, host):
        raise DatabaseError("Redis in-memory tidak didukung relasi user/GRANT database. Gunakan Docker/manual.")
    @staticmethod
    def test():
        raise DatabaseError("Redis in-memory tidak didukung.")

ENGINES = {
    "mysql": mysql,
    "postgresql": postgresql,
    "mongodb": MongoStub,
    "redis": RedisStub,
}

ACTIVE = os.environ.get("CCPANEL_DATABASE", "mysql").lower()
if ACTIVE not in ENGINES:
    ACTIVE = "mysql"

# alias error biar pengecualian lama (except mysql.MysqlError) tetap jalan
DatabaseError = mysql.MysqlError


def _engine():
    return ENGINES[ACTIVE]


def for_engine(engine: str):
    """Ambil modul engine spesifik (untuk operasi per-DB). Fallback mysql."""
    return ENGINES.get(engine.lower(), ENGINES["mysql"])


def set_active(engine: str) -> None:
    """Ganti engine aktif (runtime). Fallback mysql kalau tidak dikenal."""
    global ACTIVE
    engine = engine.lower()
    ACTIVE = engine if engine in ENGINES else "mysql"


def create_db(db_name: str, db_user: str, password: str, host: str = "localhost") -> None:
    return _engine().create_db(db_name, db_user, password, host)


def reset_password(db_user: str, password: str, host: str = "localhost") -> None:
    return _engine().reset_password(db_user, password, host)


def drop_db(db_name: str, db_user: str, host: str = "localhost") -> None:
    return _engine().drop_db(db_name, db_user, host)


def test() -> None:
    return _engine().test()