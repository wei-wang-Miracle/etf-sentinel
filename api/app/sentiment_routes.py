"""行业恐贪的本地查询、独立任务配置和异步触发接口。"""

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.db import Session
from app.jobs import launch, next_run
from app.models import Job, Run, SentimentCategory, SentimentDaily

router = APIRouter(prefix="/sentiment", tags=["行业恐贪"])


class ScheduleUpdate(BaseModel):
    """独立采集任务的北京时间配置。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/categories")
def categories():
    """概览只读取本地日数据，快照标签仅在日期和分数完全匹配时展示。"""
    with Session() as db:
        result = []
        for category in db.scalars(
            select(SentimentCategory).order_by(SentimentCategory.category_key)
        ):
            count, first, last = db.execute(
                select(
                    func.count(),
                    func.min(SentimentDaily.trade_date),
                    func.max(SentimentDaily.trade_date),
                ).where(SentimentDaily.category_key == category.category_key)
            ).one()
            latest = (
                db.get(SentimentDaily, (category.category_key, last)) if last else None
            )
            result.append(
                {
                    "category_key": category.category_key,
                    "category_name": category.category_name,
                    "index_name": category.index_name,
                    "count": count,
                    "first_date": first,
                    "last_date": last,
                    "fear_greed_score": float(latest.fear_greed_score)
                    if latest
                    else None,
                    "close_price": float(latest.close_price)
                    if latest and latest.close_price is not None
                    else None,
                    "source_label": category.snapshot_label
                    if latest
                    and category.snapshot_date == latest.trade_date
                    and category.snapshot_score == latest.fear_greed_score
                    else None,
                    "collected_at": latest.collected_at if latest else None,
                    "source": "韭圈 · industry-fear-greed",
                }
            )
        return result


@router.get("/series/{category_key}")
def series(category_key: str, start: date, end: date):
    """返回本地闭区间序列，不将缺失分数补零。"""
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    with Session() as db:
        if not db.get(SentimentCategory, category_key):
            raise HTTPException(404, "类别尚未采集，请先运行行业恐贪任务")
        rows = db.scalars(
            select(SentimentDaily)
            .where(
                SentimentDaily.category_key == category_key,
                SentimentDaily.trade_date >= start,
                SentimentDaily.trade_date <= end,
            )
            .order_by(SentimentDaily.trade_date)
        ).all()
        return [
            {
                "trade_date": r.trade_date,
                "fear_greed_score": float(r.fear_greed_score),
                "close_price": float(r.close_price)
                if r.close_price is not None
                else None,
                "collected_at": r.collected_at,
            }
            for r in rows
        ]


@router.get("/job")
def get_job():
    """返回恐贪任务配置和该任务独立的最近二十次运行。"""
    with Session() as db:
        job = db.get(Job, 2)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        runs = db.scalars(
            select(Run).where(Run.job_id == 2).order_by(Run.id.desc()).limit(20)
        ).all()
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
    """保存独立恐贪任务，不影响ETF调度。"""
    with Session() as db:
        job = db.get(Job, 2)
        if job is None:
            raise HTTPException(503, "请先升级数据库迁移")
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_job():
    """异步执行首次回补或增量采集，不需要ChatBI凭据。"""
    run_id = launch(job_id=2)
    if run_id is None:
        raise HTTPException(409, "行业恐贪采集正在运行")
    return {"run_id": run_id}
