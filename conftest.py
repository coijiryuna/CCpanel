"""Pytest configuration for test isolation."""
import os
import tempfile
from pathlib import Path
import sys

# Create a shared temp directory for all tests
_tmp = tempfile.mkdtemp(prefix="ccp-test-")
os.environ["CCPANEL_SYSTEMD_DIR"] = str(Path(_tmp) / "systemd")
os.environ["CCPANEL_PROJECT_ROOT"] = str(Path(_tmp) / "project")
os.environ["CCPANEL_WWW_ROOT"] = str(Path(_tmp) / "www")
os.environ["CCPANEL_NGINX_CONF_DIR"] = str(Path(_tmp) / "conf")
os.environ["CCPANEL_TRASH_DIR"] = str(Path(_tmp) / "trash")
os.environ["CCPANEL_DOCKER_BIN"] = "echo"
os.environ["CCPANEL_PHP_FPM_DIR"] = str(Path(_tmp) / "php")
os.environ["CCPANEL_DATA_DIR"] = str(Path(_tmp) / "data")
os.environ["CCPANEL_APT"] = "echo"
os.environ["CCPANEL_NVM_DIR"] = str(Path(_tmp) / "nvm")
os.environ["CCPANEL_GO_ROOT"] = str(Path(_tmp) / "go")
os.environ["CCPANEL_APPSTORE_LOG"] = str(Path(_tmp) / "appstore.log")
os.environ["CCPANEL_APPSTORE_CACHE"] = str(Path(_tmp) / "cache.json")
os.environ.pop("CCPANEL_APPSTORE_URL", None)

# Ensure the test directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))