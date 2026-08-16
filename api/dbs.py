"""API databases: CRUD DB + reset password. DB Type: mysql, postgresql, mongodb."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.requests import Request

from pydantic import BaseModel

from core import database as database_ops
from core import validate
from core import redis_probe
from core import mysql as mysql_ops
from core import mysql_admin as mysql_admin_ops
from core import postgresql as pg_ops
from core import pg_admin as pg_admin_ops
from core import mongo_admin as mongo_admin_ops
from core import db_service

from .deps import _log, app, check_db_access, dt_order, dt_params, dt_response, db_conn, require_auth, require_admin

class DbCreate(BaseModel):
    db_name: str
    db_user: str | None = None
    password: str | None = None
    host: str = "localhost"
    site_id: int | None = None
    db_type: str = "mysql"
    port: int | None = None

class DbResponse(BaseModel):
    id: int
    db_name: str
    db_user: str
    db_pass: str
    db_host: str
    site_id: int | None
    db_type: str
    created_at: str

def _db_row(row) -> DbResponse:
    return DbResponse(
        id=row["id"],
        db_name=row["db_name"],
        db_user=row["db_user"],
        db_pass=row["db_pass"],
        db_host=row["db_host"],
        site_id=row["site_id"],
        db_type=row["db_type"] if "db_type" in row.keys() else "mysql",
        created_at=row["created_at"],
    )

@app.post("/api/dbs", response_model=DbResponse)
def create_db(req: DbCreate, user: dict = Depends(require_auth)) -> DbResponse:
    db_name = req.db_name.strip().lower()
    db_user = (req.db_user or db_name).strip().lower()
    if not validate.valid_db_name(db_name):
        raise HTTPException(400, "Nama DB tidak valid (a-z, 0-9, _, max 64)")
    if not validate.valid_db_name(db_user):
        raise HTTPException(400, "Username tidak valid (a-z, 0-9, _, max 64)")
    host = req.host.strip()
    if host not in ("localhost", "%") and not validate.valid_ip(host):
        raise HTTPException(400, "Permission tidak valid (localhost, %, atau IP)")
    db_type = req.db_type.strip().lower()
    if db_type not in database_ops.ENGINES:
        raise HTTPException(400, f"Database engine tidak didukung: {db_type}")
    if db_type == "redis":
        # Redis: tanpa user/password/GRANT — cukup nama + port
        port = req.port or 6379
        if not (1 <= port <= 65535):
            raise HTTPException(400, "Port tidak valid (1-65535)")
        host = f"localhost:{port}"
        db_user = db_name
        password = ""
    else:
        port = None
        host = req.host.strip()
        if host not in ("localhost", "%") and not validate.valid_ip(host):
            raise HTTPException(400, "Permission tidak valid (localhost, %, atau IP)")
        password = (req.password or secrets.token_urlsafe(12)).strip()
        if not password or len(password) > 128:
            raise HTTPException(400, "Password tidak valid (1-128 char)")
    with db_conn() as conn:
        if conn.execute("SELECT 1 FROM dbs WHERE db_name = ?", (db_name,)).fetchone():
            raise HTTPException(409, "DB sudah ada")
        if req.site_id is not None:
            site = conn.execute("SELECT * FROM sites WHERE id = ?", (req.site_id,)).fetchone()
            if site is None:
                raise HTTPException(404, "Site tidak ada")
            # client hanya bisa buat DB untuk site miliknya; admin untuk site apa pun
            if user["role"] != "admin" and site["owner_id"] != user["id"]:
                raise HTTPException(403, "Bukan site Anda")
        eng = database_ops.for_engine(db_type)
        if db_type == "redis":
            # Redis in-memory: tanpa create_db/GRANT — cukup register di panel
            pass
        else:
            try:
                eng.create_db(db_name, db_user, password, host)
            except database_ops.DatabaseError as e:
                raise HTTPException(500, str(e)) from e
        owner_id = None if user["role"] == "admin" else user["id"]
        cur = conn.execute(
            "INSERT INTO dbs (site_id, db_name, db_user, db_pass, db_host, db_type, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.site_id, db_name, db_user, password, host, db_type, owner_id,
             datetime.now(timezone.utc).isoformat()),
        )
        _log(conn, user, "db.create", f"{db_name} ({db_user}@{host})")
        conn.commit()
        row = conn.execute("SELECT * FROM dbs WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _db_row(row)

@app.get("/api/dbs", response_model=list[DbResponse] | dict)
def list_dbs(
    db_type: str | None = None,
    search: str | None = None,
    start: int = 0,
    length: int = 0,
    draw: int = 0,
    order_col: str | None = None,
    order_dir: str = "asc",
    user: dict = Depends(require_auth),
) -> list[DbResponse] | dict:
    start, length, draw = dt_params(start, length, draw)
    sql = "SELECT * FROM dbs"
    conds: list[str] = []
    search_conds: list[str] = []
    args: list = []
    if user["role"] != "admin":
        conds.append("owner_id = ?")
        args.append(user["id"])
    if db_type:
        conds.append("db_type = ?")
        args.append(db_type.strip().lower())
    if search:
        s = f"%{search.strip()}%"
        search_conds.append("(db_name LIKE ? OR db_user LIKE ?)")
        args.extend([s, s])
    all_conds = conds + search_conds
    where = (" WHERE " + " AND ".join(all_conds)) if all_conds else ""
    with db_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM dbs" + (f" WHERE {' AND '.join(conds)}" if conds else ""),
            args[:len(conds)],
        ).fetchone()[0]
        filtered = conn.execute("SELECT COUNT(*) FROM dbs" + where, args).fetchone()[0]
        rows = conn.execute(
            sql + where + dt_order(["id", "db_name", "db_user", "db_type", "created_at"], order_col, order_dir)
            + (" LIMIT ? OFFSET ?" if length else ""),
            args + ([length, start] if length else []),
        ).fetchall()
    return dt_response([_db_row(r) for r in rows], start, length, total, filtered, draw)

@app.get("/api/dbs/redis/overview")
def redis_overview(user: dict = Depends(require_auth)) -> dict:
    """Live Redis: db0-db15 + key count + sample keys."""
    return redis_probe.overview()

class RedisKeyRequest(BaseModel):
    db: int = 0
    key: str
    value: str = ""
    ttl: int = -1

@app.post("/api/dbs/redis/key")
def redis_set_key(req: RedisKeyRequest, user: dict = Depends(require_auth)) -> dict:
    """Simpan/update key Redis (string). ttl>=0 = expire detik, -1 = persist."""
    res = redis_probe.set_key(req.db, req.key, req.value, req.ttl)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "gagal"))
    _log(None, user, "redis.set", f"db{req.db} {req.key}")
    return res

@app.delete("/api/dbs/redis/key")
def redis_delete_key(db: int = 0, key: str = "", user: dict = Depends(require_auth)) -> dict:
    """Hapus key Redis."""
    if not key:
        raise HTTPException(400, "key wajib diisi")
    res = redis_probe.delete_key(db, key)
    if not res.get("ok"):
        raise HTTPException(404, "key tidak ada")
    _log(None, user, "redis.delete", f"db{db} {key}")
    return res

VALID_ENGINES = {"mysql", "postgresql", "mongodb", "redis"}

@app.post("/api/dbs/{engine}/service/{action}")
def db_service_action(engine: str, action: str, user: dict = Depends(require_admin)) -> dict:
    """Start/stop/restart/reload service database via systemctl. Admin only."""
    if engine not in VALID_ENGINES:
        raise HTTPException(400, "engine tak dikenal")
    res = db_service.run(engine, action)
    if not res.get("ok"):
        raise HTTPException(500, res.get("error", "gagal"))
    _log(None, user, f"db.service.{action}", engine)
    return res

@app.get("/api/dbs/{engine}/service/status")
def db_service_status(engine: str, user: dict = Depends(require_admin)) -> dict:
    """Status service database (active/inactive/failed)."""
    if engine not in VALID_ENGINES:
        raise HTTPException(400, "engine tak dikenal")
    return {"engine": engine, "status": db_service.status(engine)}


class RootPasswordRequest(BaseModel):
    password: str


class GlobalVarRequest(BaseModel):
    variable: str
    value: str


class PresetRequest(BaseModel):
    name: str


class ConfigRequest(BaseModel):
    content: str


@app.get("/api/dbs/mysql/variables")
def mysql_variables(user: dict = Depends(require_admin)) -> dict:
    """Status + variable global MySQL saat ini."""
    try:
        return mysql_admin_ops.get_variables()
    except mysql_admin_ops.MysqlAdminError as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/dbs/mysql/variables")
def mysql_set_variable(req: GlobalVarRequest, user: dict = Depends(require_admin)) -> dict:
    """SET GLOBAL variable — runtime, hilang saat restart."""
    try:
        mysql_admin_ops.set_global(req.variable, req.value)
    except mysql_admin_ops.MysqlAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "mysql.set-global", f"{req.variable} = {req.value}")
    return {"ok": True, "variable": req.variable, "value": req.value}


@app.post("/api/dbs/mysql/optimize")
def mysql_optimize(req: PresetRequest, user: dict = Depends(require_admin)) -> dict:
    """Terapkan preset optimasi (low/medium/high) → config file + runtime."""
    try:
        r = mysql_admin_ops.apply_preset(req.name)
    except mysql_admin_ops.MysqlAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "mysql.optimize", req.name)
    return r


@app.get("/api/dbs/mysql/config")
def mysql_config(user: dict = Depends(require_admin)) -> dict:
    """Baca semua file config + override."""
    return mysql_admin_ops.read_config()


@app.post("/api/dbs/mysql/config")
def mysql_config_save(req: ConfigRequest, user: dict = Depends(require_admin)) -> dict:
    """Simpan config override 99-ccpanel.cnf. Restart mariadb dibutuhkan."""
    try:
        mysql_admin_ops.write_config(req.content)
    except mysql_admin_ops.MysqlAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "mysql.config", mysql_admin_ops.CONF_PATH.name)
    return {"ok": True, "path": str(mysql_admin_ops.CONF_PATH)}


@app.get("/api/dbs/mysql/logs")
def mysql_logs(lines: int = 200, user: dict = Depends(require_admin)) -> dict:
    """Log MySQL: error (journald), slow query, general query."""
    lines = max(10, min(lines, 1000))
    return {
        "available": mysql_admin_ops.log_available(),
        "error": mysql_admin_ops.read_error_log(lines),
        "slow": mysql_admin_ops.read_slow_log(lines),
        "general": mysql_admin_ops.read_general_log(lines),
    }


# ---------- PostgreSQL admin ----------

@app.get("/api/dbs/postgresql/variables")
def pg_variables(user: dict = Depends(require_admin)) -> dict:
    """Variable + status PostgreSQL saat ini."""
    try:
        return pg_admin_ops.get_variables()
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/dbs/postgresql/variables")
def pg_set_variable(req: GlobalVarRequest, user: dict = Depends(require_admin)) -> dict:
    """ALTER SYSTEM + reload — permanen di postgresql.auto.conf."""
    try:
        pg_admin_ops.set_global(req.variable, req.value)
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "pg.set-global", f"{req.variable} = {req.value}")
    return {"ok": True, "variable": req.variable, "value": req.value}


@app.post("/api/dbs/postgresql/optimize")
def pg_optimize(req: PresetRequest, user: dict = Depends(require_admin)) -> dict:
    """Terapkan preset optimasi (low/medium/high)."""
    try:
        r = pg_admin_ops.apply_preset(req.name)
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "pg.optimize", req.name)
    return r


@app.get("/api/dbs/postgresql/config")
def pg_config(user: dict = Depends(require_admin)) -> dict:
    """Baca postgresql.conf + conf.d + override."""
    try:
        return pg_admin_ops.read_config()
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(500, str(e)) from e


@app.post("/api/dbs/postgresql/config")
def pg_config_save(req: ConfigRequest, user: dict = Depends(require_admin)) -> dict:
    """Simpan conf.d/99-ccpanel.conf. Restart dibutuhkan."""
    try:
        pg_admin_ops.write_config(req.content)
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "pg.config", pg_admin_ops._cluster_dir().name)
    return {"ok": True}


@app.get("/api/dbs/postgresql/logs")
def pg_logs(lines: int = 200, user: dict = Depends(require_admin)) -> dict:
    """Log PostgreSQL: journald + file server log."""
    lines = max(10, min(lines, 1000))
    try:
        return {
            "available": pg_admin_ops.log_available(),
            "journal": pg_admin_ops.read_journal(lines),
            "server": pg_admin_ops.read_server_log(lines),
        }
    except pg_admin_ops.PgAdminError as e:
        raise HTTPException(500, str(e)) from e


# ---------- MongoDB admin ----------

@app.get("/api/dbs/mongodb/status")
def mongo_status(user: dict = Depends(require_admin)) -> dict:
    """Status MongoDB: version, DB list + ukuran, koneksi."""
    try:
        return mongo_admin_ops.get_status()
    except mongo_admin_ops.MongoAdminError as e:
        raise HTTPException(500, str(e)) from e


@app.get("/api/dbs/mongodb/config")
def mongo_config(user: dict = Depends(require_admin)) -> dict:
    """Baca /etc/mongod.conf (YAML) — baca saja, tak ada tulis (YAML rapuh)."""
    return mongo_admin_ops.read_config()


@app.get("/api/dbs/mongodb/logs")
def mongo_logs(lines: int = 200, user: dict = Depends(require_admin)) -> dict:
    """Log MongoDB: journald + file log."""
    lines = max(10, min(lines, 1000))
    return mongo_admin_ops.get_logs(lines)


@app.post("/api/dbs/mongodb/parameters")
def mongo_set_parameter(req: GlobalVarRequest, user: dict = Depends(require_admin)) -> dict:
    """setParameter runtime MongoDB (maxIncomingConnections, dll)."""
    try:
        mongo_admin_ops.set_parameter(req.variable, req.value)
    except mongo_admin_ops.MongoAdminError as e:
        raise HTTPException(400, str(e)) from e
    with db_conn() as conn:
        _log(conn, user, "mongo.set-parameter", f"{req.variable} = {req.value}")
    return {"ok": True, "variable": req.variable, "value": req.value}

@app.post("/api/dbs/root-password")
def set_root_password(
    req: RootPasswordRequest,
    user: dict = Depends(require_admin),
) -> dict:
    """Ganti password root DB engine aktif (mysql → root, postgresql → postgres).
    Redis/MongoDB tak punya root — 400."""
    password = req.password.strip()
    if not password or len(password) > 128:
        raise HTTPException(400, "Password tidak valid (1-128 char)")
    engine = database_ops.ACTIVE
    if engine == "mysql":
        try:
            mysql_ops.reset_password("root", password, "localhost")
        except mysql_ops.MysqlError as e:
            raise HTTPException(500, str(e)) from e
        detail = "mysql root"
    elif engine == "postgresql":
        try:
            pg_ops._psql(f"ALTER USER {pg_ops.PG_USER} WITH PASSWORD '{password}';")
        except pg_ops.PostgresqlError as e:
            raise HTTPException(500, str(e)) from e
        detail = f"postgresql {pg_ops.PG_USER}"
    else:
        raise HTTPException(400, f"Engine {engine} tidak punya root password")
    with db_conn() as conn:
        _log(conn, user, "db.root-password", detail)
    return {"ok": True}


@app.post("/api/dbs/{db_id}/reset-password", response_model=DbResponse)
def reset_db_password(db_id: int, user: dict = Depends(require_auth)) -> DbResponse:
    with db_conn() as conn:
        row = check_db_access(conn, db_id, user)
        password = secrets.token_urlsafe(12)
        eng = database_ops.for_engine(row["db_type"])
        try:
            eng.reset_password(row["db_user"], password, row["db_host"])
        except database_ops.DatabaseError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("UPDATE dbs SET db_pass = ? WHERE id = ?", (password, db_id))
        _log(conn, user, "db.reset-password", row["db_name"])
        conn.commit()
        row = conn.execute("SELECT * FROM dbs WHERE id = ?", (db_id,)).fetchone()
    return _db_row(row)

@app.delete("/api/dbs/{db_id}")
def delete_db(db_id: int, user: dict = Depends(require_auth)) -> dict:
    with db_conn() as conn:
        row = check_db_access(conn, db_id, user)
        eng = database_ops.for_engine(row["db_type"])
        try:
            eng.drop_db(row["db_name"], row["db_user"], row["db_host"])
        except database_ops.DatabaseError as e:
            raise HTTPException(500, str(e)) from e
        conn.execute("DELETE FROM dbs WHERE id = ?", (db_id,))
        _log(conn, user, "db.delete", row["db_name"])
        conn.commit()
    return {"ok": True}
