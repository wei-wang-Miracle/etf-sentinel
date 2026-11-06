"""关联指数估值本地查询及任务4管理，页面读取不请求外源。"""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import Session
from app.index_valuation import METRICS, rolling_percentiles
from app.jobs import launch, next_run
from app.models import (
    IndexCandle,
    IndexValuationDaily,
    IndexValuationSnapshot,
    InstrumentIndexLink,
    Job,
    ResearchIndex,
    Run,
)

router = APIRouter(prefix="/index-valuations", tags=["指数估值"])


class ScheduleUpdate(BaseModel):
    """任务4每日北京时间配置，不改变其他任务。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def require_index(db, code):
    """仅允许本地已配置的关联指数。"""
    item = db.get(ResearchIndex, code)
    if item is None:
        raise HTTPException(404, "指数不在当前ETF关联范围内")
    return item


def metric_rows(db, code, metric):
    """读取完整历史再计算分位，日期筛选不改变分位窗口。"""
    rows = db.scalars(
        select(IndexValuationDaily)
        .where(
            IndexValuationDaily.index_code == code,
            IndexValuationDaily.metric_key == metric,
        )
        .order_by(IndexValuationDaily.trade_date)
    ).all()
    ranks = rolling_percentiles(
        [(r.trade_date, r.metric_value, r.value_status) for r in rows]
    )
    return rows, ranks


@router.get("")
def overview():
    """返回八个关联指数的实际覆盖、五指标及独立来源分位。"""
    with Session() as db:
        result = []
        last_run = db.scalar(
            select(Run).where(Run.job_id == 4).order_by(Run.id.desc()).limit(1)
        )
        for item in db.scalars(
            select(ResearchIndex).order_by(ResearchIndex.index_code)
        ):
            snapshot = db.scalar(
                select(IndexValuationSnapshot)
                .where(IndexValuationSnapshot.index_code == item.index_code)
                .order_by(IndexValuationSnapshot.snapshot_id.desc())
                .limit(1)
            )
            payload = snapshot.source_payload if snapshot else {}
            source = payload.get("overview") or {}
            metrics = {}
            for metric, (name, unit) in METRICS.items():
                rows, ranks = metric_rows(db, item.index_code, metric)
                last = rows[-1] if rows else None
                source_rank = source.get(f"{metric}_pct")
                # 风险溢价来源分位取详情表；ROE来源未给分位时为空。
                if metric == "premium_diff":
                    source_rank = next(
                        (
                            r.get("percent")
                            for r in (payload.get("detail") or {}).get("table", [])
                            if r.get("name") == "风险溢价(差值)"
                        ),
                        None,
                    )
                metrics[metric] = {
                    "name": name,
                    "unit": unit,
                    "value": last.metric_value if last else None,
                    "value_status": last.value_status if last else "missing",
                    "trade_date": last.trade_date if last else None,
                    "first_date": rows[0].trade_date if rows else None,
                    "count": len(rows),
                    "valid_count": sum(r.value_status == "valid" for r in rows),
                    "local_percentile": ranks[-1] if ranks else None,
                    "source_percentile": source_rank,
                    "collected_at": last.collected_at if last else None,
                }
            candles = db.scalars(
                select(IndexCandle)
                .where(IndexCandle.index_code == item.index_code)
                .order_by(IndexCandle.trade_date)
            ).all()
            result.append(
                {
                    "index_code": item.index_code,
                    "index_name": item.index_name,
                    "collection_warnings": [
                        log["message"]
                        for log in last_run.logs
                        if log.get("code") == item.index_code
                        and log.get("status") == "failed"
                    ]
                    if last_run
                    else [],
                    "instrument_codes": list(
                        db.scalars(
                            select(InstrumentIndexLink.instrument_code).where(
                                InstrumentIndexLink.index_code == item.index_code
                            )
                        )
                    ),
                    "metrics": metrics,
                    "source_date": source.get("update_time"),
                    "source_stale": source.get("stale"),
                    "source_insufficient": source.get("insufficient"),
                    "source_not_applicable": source.get("not_applicable"),
                    "observed_at": snapshot.observed_at if snapshot else None,
                    "candle_count": len(candles),
                    "candle_first_date": candles[0].trade_date if candles else None,
                    "candle_last_date": candles[-1].trade_date if candles else None,
                }
            )
        return {
            "indices": result,
            "latest_run_status": last_run.status if last_run else None,
            "latest_run_at": last_run.started_at if last_run else None,
        }


@router.get("/series/{index_code}")
def series(index_code: str, start: date, end: date, metric: str = "pe"):
    """只读本地历史与指数日K；分位基于完整历史，不用来源当前分位回填过去。"""
    if start > end or metric not in METRICS:
        raise HTTPException(422, "日期范围或估值指标无效")
    with Session() as db:
        require_index(db, index_code)
        rows, ranks = metric_rows(db, index_code, metric)
        candles = db.scalars(
            select(IndexCandle)
            .where(
                IndexCandle.index_code == index_code,
                IndexCandle.trade_date >= start,
                IndexCandle.trade_date <= end,
            )
            .order_by(IndexCandle.trade_date)
        ).all()
        return {
            "series": [
                {
                    "trade_date": r.trade_date,
                    "value": r.metric_value,
                    "value_status": r.value_status,
                    "local_percentile": rank,
                    "collected_at": r.collected_at,
                }
                for r, rank in zip(rows, ranks, strict=True)
                if start <= r.trade_date <= end
            ],
            "candles": [
                {
                    "date": r.trade_date,
                    "open": r.open_price,
                    "high": r.high_price,
                    "low": r.low_price,
                    "close": r.close_price,
                    "volume": r.trading_volume,
                    "amount": r.trading_amount,
                    "change_pct": r.price_change_pct,
                    "source_updated_at": r.source_updated_at,
                    "collected_at": r.collected_at,
                }
                for r in candles
            ],
        }


@router.get("/job")
def get_job():
    """返回独立任务4的配置和最近20条运行记录。"""
    with Session() as db:
        job = db.get(Job, 4)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        runs = db.scalars(
            select(Run).where(Run.job_id == 4).order_by(Run.id.desc()).limit(20)
        )
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": True,
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


@router.put("/job")
def update_job(body: ScheduleUpdate):
    """仅更新指数估值调度，保留其他任务配置。"""
    with Session() as db:
        job = db.get(Job, 4)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_job():
    """估值无需行情凭据即可采集；行情失败在运行记录明确展示。"""
    run_id = launch(job_id=4)
    if run_id is None:
        raise HTTPException(409, "指数估值采集正在运行")
    return {"run_id": run_id}
