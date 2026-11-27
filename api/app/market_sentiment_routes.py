"""全市场恐贪与五维环境因子的本地只读查询和任务接口。"""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import Session
from app.jobs import launch, next_run
from app.market_sentiment import FACTOR_KEYS
from app.models import Job, MarketFearGreedDaily, MarketRegimeFactorDaily, Run

router = APIRouter(prefix="/market-sentiment", tags=["全市场温度"])


class ScheduleUpdate(BaseModel):
    """全市场温度任务的北京时间配置。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _changes(rows):
    if not rows:
        return {"one_day": None, "one_week": None, "one_month": None}
    latest = rows[-1]
    result = {}
    for key, days in (("one_day", 1), ("one_week", 7), ("one_month", 30)):
        baseline = next(
            (
                item
                for item in reversed(rows[:-1])
                if item.trade_date <= latest.trade_date - timedelta(days=days)
            ),
            None,
        )
        result[key] = (
            float(latest.fear_greed_score - baseline.fear_greed_score)
            if baseline is not None
            else None
        )
    return result


@router.get("/overview")
def overview():
    """返回本地最新温度、变动、子因子与真实可用覆盖范围。"""
    with Session() as db:
        totals = db.scalars(
            select(MarketFearGreedDaily).order_by(MarketFearGreedDaily.trade_date)
        ).all()
        latest = totals[-1] if totals else None
        regimes = {}
        for key in FACTOR_KEYS:
            rows = db.scalars(
                select(MarketRegimeFactorDaily)
                .where(MarketRegimeFactorDaily.factor_key == key)
                .order_by(MarketRegimeFactorDaily.trade_date)
            ).all()
            item = rows[-1] if rows else None
            regimes[key] = {
                "factor_name": item.factor_name if item else None,
                "raw_value": float(item.raw_value) if item else None,
                "source_pct_year": float(item.source_pct_year)
                if item and item.source_pct_year is not None
                else None,
                "source_pct_all": float(item.source_pct_all)
                if item and item.source_pct_all is not None
                else None,
                "trade_date": item.trade_date if item else None,
                "first_source_date": rows[0].trade_date if rows else None,
                "last_source_date": item.trade_date if item else None,
                "count": len(rows),
            }
        return {
            "latest": {
                "trade_date": latest.trade_date if latest else None,
                "fear_greed_score": float(latest.fear_greed_score) if latest else None,
                "source_label": latest.source_label if latest else None,
                "changes": _changes(totals),
            },
            "coverage": {
                "first_source_date": totals[0].trade_date if totals else None,
                "last_source_date": latest.trade_date if latest else None,
                "count": len(totals),
            },
            "regime_factors": regimes,
            "source": "韭圈 · fear-greed",
        }


@router.get("/series")
def series(start: date, end: date):
    """返回本地闭区间总分和五维子因子，不填补源缺失交易日。"""
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    with Session() as db:
        totals = db.scalars(
            select(MarketFearGreedDaily)
            .where(
                MarketFearGreedDaily.trade_date >= start,
                MarketFearGreedDaily.trade_date <= end,
            )
            .order_by(MarketFearGreedDaily.trade_date)
        ).all()
        factors = {}
        for key in FACTOR_KEYS:
            rows = db.scalars(
                select(MarketRegimeFactorDaily)
                .where(
                    MarketRegimeFactorDaily.factor_key == key,
                    MarketRegimeFactorDaily.trade_date >= start,
                    MarketRegimeFactorDaily.trade_date <= end,
                )
                .order_by(MarketRegimeFactorDaily.trade_date)
            ).all()
            factors[key] = [
                {
                    "trade_date": item.trade_date,
                    "factor_name": item.factor_name,
                    "raw_value": float(item.raw_value),
                    "source_pct_year": float(item.source_pct_year)
                    if item.source_pct_year is not None
                    else None,
                    "source_pct_all": float(item.source_pct_all)
                    if item.source_pct_all is not None
                    else None,
                    "collected_at": item.collected_at,
                }
                for item in rows
            ]
        return {
            "fear_greed": [
                {
                    "trade_date": item.trade_date,
                    "fear_greed_score": float(item.fear_greed_score),
                    "source_label": item.source_label,
                    "collected_at": item.collected_at,
                }
                for item in totals
            ],
            "regime_factors": factors,
        }


@router.get("/job")
def get_job():
    """返回任务6配置及其独立运行记录。"""
    with Session() as db:
        job = db.get(Job, 6)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        runs = db.scalars(
            select(Run).where(Run.job_id == 6).order_by(Run.id.desc()).limit(20)
        ).all()
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": True,
            "runs": [
                {
                    "id": run.id,
                    "status": run.status,
                    "trigger": run.trigger,
                    "started_at": run.started_at,
                    "ended_at": run.ended_at,
                    "logs": run.logs,
                }
                for run in runs
            ],
        }


@router.put("/job")
def update_job(body: ScheduleUpdate):
    """仅更新任务6的定时配置。"""
    with Session() as db:
        job = db.get(Job, 6)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_job():
    """手动异步采集全市场温度，运行中拒绝重入。"""
    run_id = launch(job_id=6)
    if run_id is None:
        raise HTTPException(409, "全市场温度采集正在运行")
    return {"run_id": run_id}
