"""Unit test core/tasks: buffer output, status, run_stream."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import tasks as tasks_ops

def test_append_and_status():
    key = "test:1"
    tasks_ops.append(key, "line1")
    tasks_ops.append(key, "line2")
    st = tasks_ops.status(key)
    assert st["status"] == "running"
    assert st["lines"] == ["line1", "line2"]
    assert st["done"] is False

def test_finish_ok():
    key = "test:2"
    tasks_ops.finish(key, True)
    st = tasks_ops.status(key)
    assert st["status"] == "done"
    assert st["done"] is True
    assert st["error"] == ""

def test_finish_error():
    key = "test:3"
    tasks_ops.finish(key, False, "boom")
    st = tasks_ops.status(key)
    assert st["status"] == "error"
    assert st["error"] == "boom"

def test_status_unknown_key():
    st = tasks_ops.status("nope")
    assert st["done"] is True
    assert st["status"] == "done"

def test_run_stream_success():
    key = "test:run:ok"
    tasks_ops.run_stream(["echo", "hello"], key)
    st = tasks_ops.status(key)
    assert st["status"] == "done"
    assert any("hello" in l for l in st["lines"])

def test_run_stream_failure():
    key = "test:run:fail"
    tasks_ops.run_stream(["sh", "-c", "echo err >&2; exit 3"], key)
    st = tasks_ops.status(key)
    assert st["status"] == "error"
    assert "exit code 3" in st["error"]
    assert any("err" in l for l in st["lines"])
