"""Unit test Docker manager (mock docker binary via CCPANEL_DOCKER_BIN).
Jalankan:
    .venv/bin/python -m pytest test_docker.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import docker as docker_ops


def test_containers_parse():
    rows = docker_ops.containers()
    assert rows and rows[0]["names"] == "web"
    assert rows[0]["image"] == "nginx:latest"
    assert set(rows[0].keys()) == set(docker_ops.CONTAINER_HEADERS)


def test_containers_all_flag():
    rows = docker_ops.containers(all_c=True)
    assert rows  # mock menampilkan 1 container utk -a


def test_images_parse():
    rows = docker_ops.images()
    assert rows and rows[0]["repository"] == "nginx"
    assert rows[0]["tag"] == "latest"


def test_container_action_valid():
    r = docker_ops.container_action("abc", "restart")
    assert r["ok"] and r["action"] == "restart"


def test_container_action_invalid():
    try:
        docker_ops.container_action("abc", "explode")
        raise AssertionError("harus error: aksi tidak valid")
    except docker_ops.DockerError as e:
        assert "tidak valid" in str(e)


def test_container_logs():
    text = docker_ops.container_logs("abc")
    assert "log line 1" in text


def test_pull_image():
    out = docker_ops.pull_image("nginx:latest")
    assert "Downloaded newer image" in out


def test_pull_image_invalid():
    try:
        docker_ops.pull_image("nginx; rm -rf /")
        raise AssertionError("harus error: image tidak valid")
    except docker_ops.DockerError as e:
        assert "tidak valid" in str(e)


def test_load_image():
    out = docker_ops.load_image("/tmp/img.tar")
    assert out  # mock menangkap `load -i`


def test_load_image_invalid_path():
    try:
        docker_ops.load_image("/tmp/a; rm -rf /")
        raise AssertionError("harus error: path tidak valid")
    except docker_ops.DockerError as e:
        assert "tidak valid" in str(e)


def test_create_container_full():
    cid = docker_ops.create_container("nginx:latest", "web", "8080:80", "MODE=prod", "always", "/data:/data")
    assert cid == "mocknewcontainerid"


def test_create_container_validation():
    # restart policy invalid
    try:
        docker_ops.create_container("nginx", restart="bogus")
        raise AssertionError("harus error: restart invalid")
    except docker_ops.DockerError as e:
        assert "restart" in str(e)
    # port invalid
    try:
        docker_ops.create_container("nginx", port="abc;x")
        raise AssertionError("harus error: port invalid")
    except docker_ops.DockerError as e:
        assert "port" in str(e)
    # env invalid
    try:
        docker_ops.create_container("nginx", env="NOKEY")
        raise AssertionError("harus error: env invalid")
    except docker_ops.DockerError as e:
        assert "env" in str(e).lower()


def test_engine_available():
    assert docker_ops.engine_available() is True


def test_docker_missing_bin():
    # ganti bin ke path tak ada → DockerError dengan pesan install
    old = docker_ops.DOCKER_BIN
    docker_ops.DOCKER_BIN = "/nonexistent/docker"
    try:
        try:
            docker_ops.containers()
            raise AssertionError("harus error: docker tak ada")
        except docker_ops.DockerError as e:
            assert "tidak terinstall" in str(e)
    finally:
        docker_ops.DOCKER_BIN = old
