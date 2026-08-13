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
os.environ["CCPANEL_APACHE_CONF_DIR"] = str(Path(_tmp) / "apache")
os.environ["CCPANEL_APACHE_PORTS_CONF"] = str(Path(_tmp) / "apache" / "ports.conf")
os.environ["CCPANEL_LSWS_CONF_DIR"] = str(Path(_tmp) / "lsws")
os.environ["CCPANEL_WAF_DIR"] = str(Path(_tmp) / "waf")
os.environ["CCPANEL_HOTLINK_DIR"] = str(Path(_tmp) / "hotlink")
os.environ["CCPANEL_SITEFEAT_DIR"] = str(Path(_tmp) / "sitefeat")
os.environ["CCPANEL_FTP_CONF_DIR"] = str(Path(_tmp) / "vsftpd")
# mock binary lshttpd supaya test litespeed tak butuh OpenLiteSpeed asli
_lsws_bin = Path(_tmp) / "lsws-bin"
_lsws_bin.mkdir(parents=True, exist_ok=True)
(_lsws_bin / "lshttpd").write_text("#!/bin/sh\nexit 0\n")
(_lsws_bin / "lshttpd").chmod(0o755)
os.environ["CCPANEL_LSWS_BIN"] = str(_lsws_bin / "lshttpd")
# mock php-fpm binary supaya test pool tak butuh php-fpm asli
_php_bin = Path(_tmp) / "php-bin"
_php_bin.mkdir(parents=True, exist_ok=True)
for v in ("8.1", "8.2", "8.3", "8.4"):
    (_php_bin / f"php-fpm{v}").write_text("#!/bin/sh\nexit 0\n")
    (_php_bin / f"php-fpm{v}").chmod(0o755)
# mock nginx + apachectl + systemctl supaya test vhost tak butuh service asli
_nginx_bin = Path(_tmp) / "nginx-bin"
_nginx_bin.mkdir(parents=True, exist_ok=True)
for b in ("nginx", "apachectl", "db_load", "mysql"):
    (_nginx_bin / b).write_text("#!/bin/sh\nexit 0\n")
    (_nginx_bin / b).chmod(0o755)
os.environ["PATH"] = f"{_php_bin}:{_lsws_bin}:{_nginx_bin}:" + os.environ.get("PATH", "")
os.environ["CCPANEL_TRASH_DIR"] = str(Path(_tmp) / "trash")
# mock docker binary supaya test docker manager tak butuh docker asli
_docker_bin = Path(_tmp) / "docker-bin"
_docker_bin.mkdir(parents=True, exist_ok=True)
(_docker_bin / "docker").write_text(
    "#!/bin/sh\n"
    "case \"$1\" in\n"
    "  ps) printf 'ID\\tIMAGE\\tCOMMAND\\tCREATED\\tSTATUS\\tPORTS\\tNAMES\\nabc\\tnginx:latest\\t\\\"nginx\\\"\\t2 days ago\\tUp 2 days\\t8080->80\\tweb\\n'; exit 0 ;;\n"
    "  images) printf 'REPOSITORY\\tTAG\\tID\\tCREATED\\tSIZE\\nnginx\\tlatest\\tabc\\t2 days ago\\t187MB\\n'; exit 0 ;;\n"
    "  logs) printf 'log line 1\\nlog line 2\\n'; exit 0 ;;\n"
    "  pull) echo \"Pulling $2...\"; echo \"Status: Downloaded newer image for $2\"; exit 0 ;;\n"
    "  run) echo \"mocknewcontainerid\"; exit 0 ;;\n"
    "  load) echo \"Loaded image: nginx:latest\"; exit 0 ;;\n"
    "  info) exit 0 ;;\n"
    "  *) exit 0 ;;\n"
    "esac\n"
)
(_docker_bin / "docker").chmod(0o755)
os.environ["CCPANEL_DOCKER_BIN"] = str(_docker_bin / "docker")
os.environ["CCPANEL_PHP_FPM_DIR"] = str(Path(_tmp) / "php")
os.environ["CCPANEL_DATA_DIR"] = str(Path(_tmp) / "data")
os.environ["CCPANEL_APT"] = "echo"
os.environ["CCPANEL_SYSTEMCTL"] = "echo"
os.environ["CCPANEL_NVM_DIR"] = str(Path(_tmp) / "nvm")
os.environ["CCPANEL_GO_ROOT"] = str(Path(_tmp) / "go")
os.environ["CCPANEL_APPSTORE_LOG"] = str(Path(_tmp) / "appstore.log")
os.environ["CCPANEL_APPSTORE_CACHE"] = str(Path(_tmp) / "cache.json")
os.environ.pop("CCPANEL_APPSTORE_URL", None)

# Ensure the test directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))