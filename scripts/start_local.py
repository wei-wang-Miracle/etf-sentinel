"""启动本地 PostgreSQL、迁移及前后端，退出时只清理本次子进程。"""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def process_identity(pid):
    """读取进程启动时间与命令，防止残留PID被复用后误停其他进程。"""
    # ps的日期格式受终端语言和时区影响，固定查询环境以支持跨终端重启。
    environment = {**os.environ, "LC_ALL": "C", "TZ": "Asia/Shanghai"}
    return subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "args="],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    ).stdout.strip()


@contextmanager
def running_instance(path, restart=False):
    """持有项目运行锁；重启只通知身份匹配的旧启动器并等待其清理。

    Args:
        path: 当前项目独享的运行锁文件，不保存环境变量或凭据。
        restart: 是否优雅结束已登记实例，再取得运行锁。

    Raises:
        SystemExit: 重复启动、身份无法确认或旧实例未及时退出。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # 锁文件保留原inode，不在退出时删除，避免并发启动锁住不同文件。
    with path.open("a+") as state:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not restart:
                sys.exit(
                    "本项目本地服务已运行；使用 ./scripts/start-local.sh restart 重启"
                )
            state.seek(0)
            try:
                record = json.load(state)
                pid = record["pid"]
                identity = record["identity"]
                if (
                    type(pid) is not int
                    or pid <= 1
                    or not identity
                    or process_identity(pid) != identity
                ):
                    raise ValueError("进程身份不匹配")
            except (ValueError, KeyError, TypeError):
                sys.exit(
                    "无法确认旧启动器身份；请在原终端按 Ctrl+C 后重新启动，不会停止未知进程"
                )
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            print("等待旧启动器停止前后端，PostgreSQL 保持运行…", flush=True)
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(state, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        sys.exit("旧启动器30秒内未退出，重启取消；请检查原终端日志")
                    time.sleep(0.1)
        try:
            state.seek(0)
            state.truncate()
            json.dump(
                {"pid": os.getpid(), "identity": process_identity(os.getpid())}, state
            )
            state.flush()
            yield
        finally:
            state.seek(0)
            state.truncate()
            state.flush()
            fcntl.flock(state, fcntl.LOCK_UN)


def main():
    """解析启动或重启命令，在项目独占锁内完成初始化和服务运行。"""
    parser = argparse.ArgumentParser(description="启动或重启本地前后端，保留PostgreSQL")
    parser.add_argument(
        "command", nargs="?", default="start", choices=("start", "restart")
    )
    args = parser.parse_args()

    def stop(signum, frame):
        """初始化阶段也响应重启请求并释放运行锁。"""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with running_instance(
            ROOT / ".local" / "start-local.lock", args.command == "restart"
        ):
            start_services()
    except KeyboardInterrupt:
        pass


def check_ports(ports):
    """允许已关闭连接的TIME_WAIT，但拒绝仍在监听的未知服务。"""
    for port in ports:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                sys.exit(
                    f"端口 {port} 已被占用，请先停止对应本地服务或调整 .env；脚本不会杀死既有进程"
                )


def start_services():
    """验证端口后启动本地服务，任一服务退出则停止另一服务。"""
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")
    os.environ.setdefault("PGHOST", "127.0.0.1")
    os.environ.setdefault("PGPORT", "55432")
    api_port = int(os.getenv("API_PORT", "8000"))
    web_port = int(os.getenv("WEB_PORT", "5173"))
    if api_port == web_port:
        sys.exit("API_PORT 与 WEB_PORT 不能相同")
    check_ports((api_port, web_port))
    if os.environ["PGHOST"] not in ("127.0.0.1", "localhost"):
        sys.exit("本地启动脚本仅连接本机 PostgreSQL，请设置 PGHOST=127.0.0.1")
    compose = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.local.yaml"]
    # 可复用本机已启动的同一项目库，不接管或修改它的容器配置。
    with socket.socket() as sock:
        reachable = sock.connect_ex(("127.0.0.1", int(os.environ["PGPORT"]))) == 0
    if not reachable:
        subprocess.run(
            [*compose, "up", "-d", "--wait", "--wait-timeout", "90", "postgres"],
            check=True,
        )
    sys.path.insert(0, str(ROOT / "api"))
    from app.db import engine
    from sqlalchemy import text

    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ROOT / "api/alembic.ini"),
            "upgrade",
            "head",
        ],
        check=True,
    )
    os.environ["API_PROXY_TARGET"] = f"http://127.0.0.1:{api_port}"
    children = []

    def stop(signum, frame):
        """将终止请求转交主流程，保证统一回收子进程组。"""
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                ],
                cwd=ROOT / "api",
                start_new_session=True,
            )
        )
        children.append(
            subprocess.Popen(
                [
                    "npm",
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(web_port),
                    "--strictPort",
                ],
                cwd=ROOT / "web",
                start_new_session=True,
            )
        )
        print(
            f"前端：http://localhost:{web_port}\nAPI：http://localhost:{api_port}/docs\n按 Ctrl+C 停止前后端，PostgreSQL 和数据保留。",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("前端或后端已退出，请检查上方日志")
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    main()
