"""API 入口，仅提供工程运行所需的健康检查。"""

from fastapi import FastAPI

app = FastAPI(title="ETF Sentinel API", version="0.1.0")


@app.get("/health", tags=["系统"])
def health() -> dict[str, str]:
    """返回进程存活状态，不代表数据库或行情数据就绪。"""
    return {"status": "ok"}
