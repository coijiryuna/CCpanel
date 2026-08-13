import os
from pathlib import Path
from fastapi.testclient import TestClient

def test_global_exception_handler():
    # Import server to register routes and exception handlers
    from server import app

    log_file = Path("/tmp/ccpanel_error.log")
    if log_file.exists():
        try:
            log_file.unlink()
        except Exception:
            pass

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/test-trigger-error")
    assert response.status_code == 500
    assert "This is a simulated server error" in response.json()["detail"]

    # Verify that it wrote to /tmp/ccpanel_error.log
    assert log_file.exists()
    log_content = log_file.read_text()
    assert "ValueError: This is a simulated server error" in log_content
    assert "GET" in log_content
    assert "/api/test-trigger-error" in log_content

    # Clean up
    try:
        log_file.unlink()
    except Exception:
        pass
