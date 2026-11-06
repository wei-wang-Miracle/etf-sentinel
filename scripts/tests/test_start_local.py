"""验证本地进程管理，不连接数据库或停止真实服务。"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "start_local.py"
spec = importlib.util.spec_from_file_location("start_local", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def managed(tmp_path):
    """用独立进程模拟持锁的旧启动器，退出时记录清理完成。"""
    state = tmp_path / "run.lock"
    cleaned = tmp_path / "cleaned"
    code = f"""
import runpy, signal, time
from pathlib import Path
module = runpy.run_path({str(SCRIPT)!r})
def stop(*_):
    raise SystemExit(0)
signal.signal(signal.SIGTERM, stop)
with module["running_instance"](Path({str(state)!r})):
    print("ready", flush=True)
    try:
        time.sleep(30)
    finally:
        Path({str(cleaned)!r}).touch()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        yield process, state, cleaned
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def test_duplicate_start_refused(managed):
    """重复启动不能接管或停止已运行实例。"""
    process, state, _ = managed
    with pytest.raises(SystemExit, match="已运行"), launcher.running_instance(state):
        pytest.fail("不应取得运行锁")
    assert process.poll() is None


def test_restart_waits_for_cleanup(managed):
    """restart 等旧实例清理完成后才获得锁。"""
    process, state, cleaned = managed
    with launcher.running_instance(state, restart=True):
        assert cleaned.exists()
        assert process.wait(timeout=5) == 0
        assert json.loads(state.read_text())["pid"] != process.pid
    assert state.read_text() == ""


def test_stale_metadata_is_safe(tmp_path):
    """崩溃残留但未持锁的元数据不阻止重新启动。"""
    state = tmp_path / "run.lock"
    state.write_text('{"pid": 1, "identity": "old"}')
    with launcher.running_instance(state, restart=True):
        assert json.loads(state.read_text())["pid"] != 1


def test_identity_mismatch_does_not_signal(managed):
    """进程身份不符时拒绝重启，避免向复用PID发送信号。"""
    process, state, _ = managed
    record = json.loads(state.read_text())
    record["identity"] = "过期进程身份"
    state.write_text(json.dumps(record))
    with (
        pytest.raises(SystemExit, match="身份"),
        launcher.running_instance(state, restart=True),
    ):
        pytest.fail("不应接管身份不符的进程")
    assert process.poll() is None


def test_recent_connections_do_not_block_restart():
    """旧HTTP连接的TIME_WAIT不能误报为仍有服务占用端口。"""
    import socket

    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen()
        with socket.create_connection(("127.0.0.1", port)) as client:
            connection, _ = server.accept()
            connection.close()
            assert client.recv(1) == b""
    launcher.check_ports([port])


def test_unknown_listener_is_preserved():
    """未知服务仍在监听时明确退出，不能停止它。"""
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        with pytest.raises(SystemExit, match="已被占用"):
            launcher.check_ports([port])
        with socket.create_connection(("127.0.0.1", port)):
            pass


def test_process_identity_is_independent_of_terminal_locale(monkeypatch):
    """中文终端和不同时区必须识别为同一个进程。"""
    import os

    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    expected = launcher.process_identity(os.getpid())
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    monkeypatch.setenv("TZ", "UTC")
    assert launcher.process_identity(os.getpid()) == expected
