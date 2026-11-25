"""ETF 日行情配置、任务管理与本地行情查询 API。"""

import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.account_routes import router as account_router
from app.algorithm_templates import turning_events, turning_profile
from app.backtest_data import (
    front_adjusted_ohlc_rows,
    indicator_ohlc_rows,
    validate_market,
)
from app.backtest_routes import router as backtest_router
from app.collection import now
from app.db import Session
from app.index_valuation_routes import router as index_valuation_router
from app.jobs import launch, next_run, recover_interrupted, scheduler
from app.models import BacktestSource, Candle, Instrument, Job, Run
from app.national_team_routes import router as national_team_router
from app.research_routes import router as research_router
from app.review_routes import router as review_router
from app.sentiment_routes import router as sentiment_router
from app.strategy_lab import router as strategy_lab_router
from app.strategy_workbench import router as strategy_workbench_router


@asynccontextmanager
async def lifespan(app):
    """随应用启动调度，关闭时停止后续调度检查。"""
    recover_interrupted()
    recover_interrupted(2)
    recover_interrupted(3)
    recover_interrupted(4)
    recover_interrupted(5)
    stop = threading.Event()
    thread = threading.Thread(target=scheduler, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=2)


app = FastAPI(title="ETF Sentinel API", version="0.3.0", lifespan=lifespan)
app.include_router(account_router)
app.include_router(backtest_router)
app.include_router(sentiment_router)
app.include_router(national_team_router)
app.include_router(index_valuation_router)
app.include_router(research_router)
app.include_router(review_router)
app.include_router(strategy_lab_router)
app.include_router(strategy_workbench_router)


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
                os.getenv("CHATBI_TOKEN")
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
    if not os.getenv("CHATBI_TOKEN"):
        raise HTTPException(422, "后端数据源凭据尚未配置")
    run_id = launch()
    if run_id is None:
        raise HTTPException(409, "采集任务正在运行")
    return {"run_id": run_id}


@app.get("/candles/{code}")
def candles(code: str, start: date, end: date):
    """查询图表用前复权日 K，不触发外部采集。"""
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
        raw_rows = [
            {
                "date": r.date,
                "open": str(r.open),
                "high": str(r.high),
                "low": str(r.low),
                "close": str(r.close),
                "adjusted_close": str(r.adjusted_close) if r.adjusted_close is not None else None,
                "volume": float(r.volume),
                "amount": float(r.amount),
                "source_updated_at": r.source_updated_at,
                "collected_at": r.collected_at,
            }
            for r in rows
        ]
        try:
            displayed = front_adjusted_ohlc_rows(raw_rows)
        except ValueError as exc:
            raise HTTPException(422, f"行情复权资料未通过校验：{exc}") from None
        previous_close = None
        result = []
        for row in displayed:
            close = float(row["close"])
            change_pct = (
                (close / previous_close - 1) * 100
                if previous_close is not None else None
            )
            result.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": close,
                "volume": row["volume"],
                "amount": row["amount"],
                "change_pct": change_pct,
                "source_updated_at": row["source_updated_at"],
                "collected_at": row["collected_at"],
            })
            previous_close = close
        return result


@app.get("/candles/{code}/turning-events")
def candle_turning_events(code: str, start: date, end: date):
    """读取行情图上的策略顶底确认日，沿用策略的日行情与权益校验。"""
    if start > end or not re.fullmatch(r"\d{6}", code):
        raise HTTPException(422, "代码或日期范围无效")
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if not db.get(Instrument, code):
            raise HTTPException(404, "标的尚未配置")
        latest = db.scalar(
            select(func.max(Candle.date)).where(Candle.code == code, Candle.date <= end)
        )
        if latest is None or latest < start:
            return {"events": [], "data_cutoff": None, "partial": False}
        source = db.get(BacktestSource, code)
        if source is None:
            raise HTTPException(422, "尚无已核验权益资料")
        cutoff = min(latest, source.checked_through_date)
        partial = cutoff < latest
        if cutoff < start:
            return {"events": [], "data_cutoff": None, "partial": partial}
        candles = list(db.scalars(
            select(Candle)
            .where(Candle.code == code, Candle.date <= cutoff)
            .order_by(Candle.date)
        ))
        rows = [
            {
                "trade_date": str(row.date),
                **{
                    key: str(getattr(row, key)) if getattr(row, key) is not None else None
                    for key in ("open", "high", "low", "close", "adjusted_close", "volume")
                },
            }
            for row in candles
        ]
        try:
            validate_market(rows, source.corporate_actions, allow_splits=True)
            indicator_rows = indicator_ohlc_rows(rows, source.corporate_actions)
        except ValueError as exc:
            raise HTTPException(422, f"行情或权益资料未通过校验：{exc}") from None

    events = turning_events(
        indicator_rows,
        [],
        turning_profile(code)["parameters"],
    )
    return {
        "events": [
            {"date": day, "kind": kind}
            for day, kind in events.items()
            if day >= start.isoformat()
        ],
        "data_cutoff": rows[-1]["trade_date"],
        "partial": partial,
    }
