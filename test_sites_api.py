import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import app
from api.deps import require_auth, get_db

def test_create_site_with_ftp_and_db():
    # Bypass auth
    app.dependency_overrides[require_auth] = lambda: {"id": 1, "username": "admin", "role": "admin"}

    # Seed the admin user in the DB
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role, created_at) "
            "VALUES (1, 'admin', 'abc', 'admin', '2026-08-13')"
        )
        conn.commit()

    client = TestClient(app)
    
    # 1. Create a site with FTP and DB enabled
    payload = {
        "domain": "testftpdb.com",
        "project_type": "php",
        "php_version": "php8.1",
        "create_ftp": True,
        "ftp_username": "testftp",
        "ftp_password": "testftppassword",
        "create_db": True,
        "db_name": "testdb",
        "db_user": "testdbuser",
        "db_pass": "testdbpassword"
    }
    
    response = client.post("/api/sites", json=payload)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["domain"] == "testftpdb.com"
    
    # Verify in DB
    with get_db() as conn:
        site = conn.execute("SELECT * FROM sites WHERE domain = ?", ("testftpdb.com",)).fetchone()
        assert site is not None
        
        ftp = conn.execute("SELECT * FROM ftp_accounts WHERE site_id = ?", (site["id"],)).fetchone()
        assert ftp is not None
        assert ftp["username"] == "testftp"
        
        db = conn.execute("SELECT * FROM dbs WHERE site_id = ?", (site["id"],)).fetchone()
        assert db is not None
        assert db["db_name"] == "testdb"

    # Clean up overrides
    app.dependency_overrides.clear()
