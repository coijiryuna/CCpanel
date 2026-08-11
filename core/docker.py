"""Docker manager: list + aksi container/image via CLI docker.

Hanya operasi umum yang dipakai sehari-hari hosting panel: list container,
start/stop/restart/remove, log tail, list image. Bukan full Docker Manager
(image build/pull/network/volume/repository) — YAGNI, docker tak terinstall
di sebagian besar VPS hosting.

Pola: subprocess argumen-list (tanpa shell), `docker` dioverride env utk tes.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Any

DOCKER_BIN = os.environ.get("CCPANEL_DOCKER_BIN", "docker")


class DockerError(Exception):
    pass


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise DockerError("docker tidak terinstall (pasang via App Store)") from None
    except subprocess.TimeoutExpired:
        raise DockerError(f"docker {args[-1] if args else ''} timeout") from None


def _check(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or f"docker {what} gagal")


def _parse_table(out: str, headers: list[str]) -> list[dict[str, str]]:
    """Parse output `docker ps --format`-style: baris pertama = header, sisanya value."""
    rows: list[dict[str, str]] = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        cells = [c.strip() for c in line.split("\t")]
        # skip baris header (docker versi tertentu bisa tetap cetak header)
        if cells[:1] and cells[0].lower() == headers[0]:
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


CONTAINER_HEADERS = ["id", "image", "command", "created", "status", "ports", "names"]
IMAGE_HEADERS = ["repository", "tag", "id", "created", "size"]


def containers(all_c: bool = False) -> list[dict[str, str]]:
    """List container. `docker ps [-a]` --format dengan tab separator."""
    fmt = "\t".join("{{." + h + "}}" for h in CONTAINER_HEADERS)
    args = [DOCKER_BIN, "ps", "--format", fmt]
    if all_c:
        args.append("-a")
    res = _run(args)
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or "docker ps gagal")
    return _parse_table(res.stdout, CONTAINER_HEADERS)


def images() -> list[dict[str, str]]:
    """List image. `docker images` --format."""
    fmt = "\t".join("{{." + h + "}}" for h in IMAGE_HEADERS)
    res = _run([DOCKER_BIN, "images", "--format", fmt])
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or "docker images gagal")
    return _parse_table(res.stdout, IMAGE_HEADERS)


def pull_image(image: str) -> str:
    """Pull image dari registry. `docker pull <image>`. Output progress bar."""
    name = (image or "").strip()
    if not name or any(c in name for c in " &;|"):
        raise DockerError("Nama image tidak valid")
    res = _run([DOCKER_BIN, "pull", name], timeout=600)
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or f"docker pull {name} gagal")
    return res.stdout or res.stderr

def load_image(tar_path: str) -> str:
    """Import image dari file tar lokal (hasil `docker save`). `docker load -i`."""
    p = (tar_path or "").strip()
    if not p or any(c in p for c in " &;|"):
        raise DockerError("Path file tar tidak valid")
    res = _run([DOCKER_BIN, "load", "-i", p], timeout=600)
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or "docker load gagal")
    return res.stdout or res.stderr


def create_container(
    image: str,
    name: str = "",
    port: str = "",
    env: str = "",
    restart: str = "no",
    volume: str = "",
    cmd: str = "",
) -> str:
    """Buat container baru. `docker run -d [--name] [-p] [-e] [--restart] [-v] image [cmd]`.

    port: "HOST:CONTAINER" (mis. 8080:80) atau list dipisah koma.
    env:  "KEY=value" atau list dipisah koma.
    volume: "host:container" atau list dipisah koma.
    """
    name = (name or "").strip()
    port = (port or "").strip()
    env = (env or "").strip()
    volume = (volume or "").strip()
    cmd = (cmd or "").strip()
    if restart not in ("no", "always", "unless-stopped", "on-failure"):
        raise DockerError(f"Kebijakan restart tidak valid: {restart}")
    if not image:
        raise DockerError("Image wajib diisi")
    if any(c in image for c in " &;|"):
        raise DockerError("Nama image tidak valid")

    args = [DOCKER_BIN, "run", "-d"]
    if name:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name):
            raise DockerError("Nama container tidak valid (huruf/angka/._-)")
        args += ["--name", name]
    for p in [x.strip() for x in port.split(",") if x.strip()]:
        if not re.fullmatch(r"[0-9]{1,5}(:[0-9]{1,5}(/tcp|/udp)?)?", p):
            raise DockerError(f"Mapping port tidak valid: {p}")
        args += ["-p", p]
    for e in [x.strip() for x in env.split(",") if x.strip()]:
        if "=" not in e or any(c in e for c in " &;|"):
            raise DockerError(f"Env tidak valid: {e}")
        args += ["-e", e]
    if restart != "no":
        args += ["--restart", restart]
    for v in [x.strip() for x in volume.split(",") if x.strip()]:
        if ":" not in v or any(c in v for c in " &;|"):
            raise DockerError(f"Volume tidak valid: {v}")
        args += ["-v", v]
    args.append(image)
    if cmd:
        args.append(cmd)
    res = _run(args, timeout=120)
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or f"docker run {image} gagal")
    return res.stdout.strip() or res.stderr.strip()


def container_action(container_id: str, action: str) -> dict[str, Any]:
    """start/stop/restart/remove (rm -f utk force). Container oleh compose
    dipegang compose — operasi manual di sini untuk container standalone."""
    if action not in ("start", "stop", "restart", "remove"):
        raise DockerError(f"Aksi tidak valid: {action}")
    cmd = ["rm", "-f"] if action == "remove" else [action]
    res = _run([DOCKER_BIN, *cmd, container_id], timeout=60)
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or f"docker {action} {container_id} gagal")
    return {"ok": True, "action": action, "id": container_id}


def container_logs(container_id: str, lines: int = 200) -> str:
    """Tail log container. `docker logs --tail N container`."""
    res = _run([DOCKER_BIN, "logs", "--tail", str(lines), container_id])
    if res.returncode != 0:
        raise DockerError(res.stderr.strip() or "docker logs gagal")
    return res.stdout


def engine_available() -> bool:
    """Cek docker binary + daemon hidup (info). Untuk badge status."""
    res = _run([DOCKER_BIN, "info"])
    return res.returncode == 0
