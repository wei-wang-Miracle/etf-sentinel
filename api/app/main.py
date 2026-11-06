"""ETF 日行情配置、任务管理与本地行情查询 API。"""

import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.backtest_routes import router as backtest_router
from app.collection import now
from app.db import Session
from app.jobs import launch, next_run, recover_interrupted, scheduler
from app.models import Candle, Instrument, Job, Run
from app.national_team_routes import router as national_team_router
from app.sentiment_routes import router as sentiment_router


@asynccontextmanager
async def lifespan(app):
    """随应用启动调度，关闭时停止后续调度检查。"""
    recover_interrupted()
    recover_interrupted(2)
    recover_interrupted(3)
    stop = threading.Event()
    thread = threading.Thread(target=scheduler, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=2)


app = FastAPI(title="ETF Sentinel API", version="0.3.0", lifespan=lifespan)
app.include_router(backtest_router)
app.include_router(sentiment_router)
app.include_router(national_team_router)


class InstrumentUpdate(BaseModel):
    """标的采集开关与回补起点。"""

    enabled: bool
    start_date: date


class JobUpdate(BaseModel):
    """每日北京时间与调度开关。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@app.get("/health", tags=["系统"])
def health():
    """仅返回进程存活状态。"""
    return {"status": "ok"}


@app.get("/instruments")
def instruments():
    """返回标的配置及已持久化行情覆盖范围。"""
    with Session() as db:
        result = []
        for item in db.scalars(select(Instrument).order_by(Instrument.code)):
            count, first, last = db.execute(
                select(
                    func.count(), func.min(Candle.date), func.max(Candle.date)
                ).where(Candle.code == item.code)
            ).one()
            result.append(
                {
                    "code": item.code,
                    "name": item.name,
                    "enabled": item.enabled,
                    "start_date": item.start_date,
                    "count": count,
                    "first_date": first,
                    "last_date": last,
                    "source": "ChatBI · daily_ohlcv_etf",
                }
            )
        return result


@app.put("/instruments/{code}")
def update_instrument(code: str, body: InstrumentUpdate):
    """更新采集配置，不删除历史行情。"""
    if body.start_date >= now().date():
        raise HTTPException(422, "历史起始日期必须早于今天")
    with Session() as db:
        item = db.get(Instrument, code)
        if not item:
            raise HTTPException(404, "标的尚未配置")
        item.enabled, item.start_date = body.enabled, body.start_date
        db.commit()
    return {"saved": True}


@app.get("/job")
def get_job():
    """返回任务配置、下次执行时间和最近运行记录。"""
    with Session() as db:
        job = db.get(Job, 1)
        runs = db.scalars(
            select(Run).where(Run.job_id == 1).order_by(Run.id.desc()).limit(20)
        ).all()
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": bool(
                os.getenv("CHATBI_TOKEN") and os.getenv("CHATBI_ACCESS_CODE")
            ),
            "runs": [
                {
                    "id": r.id,
                    "status": r.status,
                    "trigger": r.trigger,
                    "started_at": r.started_at,
                    "ended_at": r.ended_at,
                    "logs": r.logs,
                }
                for r in runs
            ],
        }


@app.put("/job")
def update_job(body: JobUpdate):
    """持久化任务时间与启停设置。"""
    with Session() as db:
        job = db.get(Job, 1)
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@app.post("/job/run", status_code=202)
def run_job():
    """手动触发异步采集，重复触发返回冲突。"""
    if not os.getenv("CHATBI_TOKEN") or not os.getenv("CHATBI_ACCESS_CODE"):
        raise HTTPException(422, "后端数据源凭据尚未配置")
    run_id = launch()
    if run_id is None:
        raise HTTPException(409, "采集任务正在运行")
    return {"run_id": run_id}


@app.get("/candles/{code}")
def candles(code: str, start: date, end: date):
    """查询本地原始日 K，不触发外部采集。"""
    if start > end or not re.fullmatch(r"\d{6}", code):
        raise HTTPException(422, "代码或日期范围无效")
    with Session() as db:
        if not db.get(Instrument, code):
            raise HTTPException(404, "标的尚未配置")
        rows = db.scalars(
            select(Candle)
            .where(Candle.code == code, Candle.date >= start, Candle.date <= end)
            .order_by(Candle.date)
        ).all()
        return [
            {
                "date": r.date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
                "amount": float(r.amount),
                "change_pct": float(r.change_pct) if r.change_pct is not None else None,
                "source_updated_at": r.source_updated_at,
                "collected_at": r.collected_at,
            }
            for r in rows
        ]
