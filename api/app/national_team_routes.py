"""国家队估算比例与本地日K对照查询，以及独立任务管理。"""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db import Session
from app.jobs import launch, next_run
from app.models import Candle, Job, NationalTeamDaily, NationalTeamInstrument, Run
from app.national_team import ESTIMATION_START, INSTRUMENT_CODES

router = APIRouter(prefix="/national-team", tags=["国家队持仓"])


class ScheduleUpdate(BaseModel):
    """任务3的每日北京时间配置。

    Attributes:
        enabled: 是否启用后续每日调度，不禁止手动采集。
        time: 北京时间HH:mm。
    """

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/instruments")
def instruments():
    """查询十八只源标的的本地概览与实际数据日期，不请求外部数据。"""
    with Session() as db:
        result = []
        items = {
            item.instrument_code: item
            for item in db.scalars(select(NationalTeamInstrument))
        }
        for code in INSTRUMENT_CODES:
            item = items.get(code)
            if item is None:
                continue
            count, first, last = db.execute(
                select(
                    func.count(),
                    func.min(NationalTeamDaily.trade_date),
                    func.max(NationalTeamDaily.trade_date),
                ).where(NationalTeamDaily.instrument_code == code)
            ).one()
            latest = db.get(NationalTeamDaily, (code, last)) if last else None
            candle_last = db.scalar(
                select(func.max(Candle.date)).where(Candle.code == code)
            )
            result.append(
                {
                    "instrument_code": code,
                    "instrument_name": item.instrument_name,
                    "index_name": item.index_name,
                    "count": count,
                    "first_date": first,
                    "last_date": last,
                    "estimated_holding_pct": float(latest.estimated_holding_pct)
                    if latest and latest.estimated_holding_pct is not None
                    else None,
                    "reference_holding_pct": float(item.reference_holding_pct)
                    if item.reference_holding_pct is not None
                    else None,
                    "estimation_start_date": item.estimation_start_date,
                    "source_available": item.source_available,
                    "source_url": item.source_url,
                    "last_success_at": item.last_success_at,
                    "candle_last_date": candle_last,
                }
            )
        return result


@router.get("/series/{instrument_code}")
def series(instrument_code: str, start: date, end: date):
    """日期仅过滤固定基准下的已存比例，同代码日K独立查询，缺失不补零。"""
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    with Session() as db:
        item = db.get(NationalTeamInstrument, instrument_code)
        if not item:
            raise HTTPException(404, "基金尚未采集，请先运行国家队持仓任务")
        holdings = db.scalars(
            select(NationalTeamDaily)
            .where(
                NationalTeamDaily.instrument_code == instrument_code,
                NationalTeamDaily.trade_date >= start,
                NationalTeamDaily.trade_date <= end,
            )
            .order_by(NationalTeamDaily.trade_date)
        ).all()
        candles = db.scalars(
            select(Candle)
            .where(
                Candle.code == instrument_code,
                Candle.date >= start,
                Candle.date <= end,
            )
            .order_by(Candle.date)
        ).all()
        return {
            "estimation_start_date": item.estimation_start_date,
            "holdings": [
                {
                    "trade_date": r.trade_date,
                    "estimated_holding_pct": float(r.estimated_holding_pct)
                    if r.estimated_holding_pct is not None
                    else None,
                    "collected_at": r.collected_at,
                }
                for r in holdings
            ],
            "candles": [
                {
                    "date": r.date,
                    "open": float(r.open),
                    "high": float(r.high),
                    "low": float(r.low),
                    "close": float(r.close),
                    "volume": float(r.volume),
                    "amount": float(r.amount),
                    "change_pct": float(r.change_pct)
                    if r.change_pct is not None
                    else None,
                    "source_updated_at": r.source_updated_at,
                    "collected_at": r.collected_at,
                }
                for r in candles
            ],
        }


@router.get("/job")
def get_job():
    """返回任务3独立配置、基准与最近二十次执行记录。"""
    with Session() as db:
        job = db.get(Job, 3)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        runs = db.scalars(
            select(Run).where(Run.job_id == 3).order_by(Run.id.desc()).limit(20)
        )
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": True,
            "estimation_start_date": ESTIMATION_START,
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
    """仅修改任务3，不改变ETF行情和行业恐贪调度。"""
    with Session() as db:
        job = db.get(Job, 3)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_job():
    """手动异步核验并增量入库，运行中返回冲突。"""
    run_id = launch(job_id=3)
    if run_id is None:
        raise HTTPException(409, "国家队持仓采集正在运行")
    return {"run_id": run_id}
