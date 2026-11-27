"""配置内 ETF 档案和日度份额流的只读接口及任务7控制面。"""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db import Session
from app.jobs import launch, next_run
from app.models import EtfCatalogProfile, EtfFlowDaily, Instrument, Job, Run

router = APIRouter(prefix="/etf-flows", tags=["ETF档案与份额流"])


class ScheduleUpdate(BaseModel):
    """任务7的每日执行开关和北京时间。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _require_instrument(db, code: str) -> Instrument:
    item = db.get(Instrument, code)
    if item is None:
        raise HTTPException(404, "标的尚未配置")
    return item


@router.get("/{code}/summary")
def summary(code: str):
    """返回本地档案与最新资金份额截面，不把缺失伪造为零。"""
    with Session() as db:
        instrument = _require_instrument(db, code)
        profile = db.get(EtfCatalogProfile, code)
        latest = db.scalar(
            select(EtfFlowDaily)
            .where(EtfFlowDaily.instrument_code == code)
            .order_by(EtfFlowDaily.trade_date.desc())
            .limit(1)
        )
        first, last, count = db.execute(
            select(
                func.min(EtfFlowDaily.trade_date),
                func.max(EtfFlowDaily.trade_date),
                func.count(),
            ).where(EtfFlowDaily.instrument_code == code)
        ).one()
        return {
            "instrument": {
                "code": instrument.code,
                "name": instrument.name,
                "enabled": instrument.enabled,
            },
            "profile": {
                "fund_full_name": profile.fund_full_name,
                "category_primary": profile.category_primary,
                "category_tag": profile.category_tag,
                "tracking_index_code": profile.tracking_index_code,
                "tracking_index_name": profile.tracking_index_name,
                "index_corr": profile.index_corr,
                "setup_date": profile.setup_date,
                "management_fee_pct": profile.management_fee_pct,
                "custody_fee_pct": profile.custody_fee_pct,
                "linked_otc_code": profile.linked_otc_code,
                "source_url": profile.source_url,
                "collected_at": profile.collected_at,
            }
            if profile
            else None,
            "latest": _flow_payload(latest) if latest else None,
            "coverage": {
                "first_trade_date": first,
                "last_trade_date": last,
                "count": count,
            },
            "source": "FundDB ETF档案与规模份额截面",
        }


@router.get("/{code}/series")
def series(code: str, start: date, end: date):
    """返回本地已采集的截面序列；源缺日保持缺失。"""
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    with Session() as db:
        _require_instrument(db, code)
        rows = db.scalars(
            select(EtfFlowDaily)
            .where(
                EtfFlowDaily.instrument_code == code,
                EtfFlowDaily.trade_date >= start,
                EtfFlowDaily.trade_date <= end,
            )
            .order_by(EtfFlowDaily.trade_date)
        ).all()
        return {"series": [_flow_payload(row) for row in rows]}


def _flow_payload(row: EtfFlowDaily) -> dict:
    return {
        "trade_date": row.trade_date,
        "unit_shares_100m": row.unit_shares_100m,
        "aum_100m": row.aum_100m,
        "net_share_flow_7d_100m": row.net_share_flow_7d_100m,
        "net_share_flow_30d_100m": row.net_share_flow_30d_100m,
        "discount_premium_pct": row.discount_premium_pct,
        "purchase_status": row.purchase_status,
        "redeem_status": row.redeem_status,
        "collected_at": row.collected_at,
    }


@router.get("/job")
def get_job():
    """返回任务7配置与独立运行记录。"""
    with Session() as db:
        job = db.get(Job, 7)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        runs = db.scalars(
            select(Run).where(Run.job_id == 7).order_by(Run.id.desc()).limit(20)
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
    """更新任务7定时配置。"""
    with Session() as db:
        job = db.get(Job, 7)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_job():
    """手动异步采集配置内 ETF 档案和份额流。"""
    run_id = launch(job_id=7)
    if run_id is None:
        raise HTTPException(409, "ETF档案与份额流采集正在运行")
    return {"run_id": run_id}
