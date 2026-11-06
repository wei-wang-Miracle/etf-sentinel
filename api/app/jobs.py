"""独立任务后台执行与数据库级互斥调度。"""

import logging
import os
import threading
from datetime import timedelta

from sqlalchemy import select, text

from app.collection import collect, now
from app.db import Session, engine
from app.index_collection import collect_indices
from app.models import Job, Run
from app.national_team import collect_national_team
from app.sentiment import collect_sentiment

logger = logging.getLogger(__name__)
LOCK_ID = 510500512100


def launch(trigger="manual", job_id=1):
    """持有独立数据库连接锁直到任务结束，跨进程防止重入。"""
    collectors = {1: collect, 2: collect_sentiment, 3: collect_national_team, 4: collect_indices}
    if job_id not in collectors:
        raise ValueError("未知采集任务")
    lock_id = LOCK_ID + job_id - 1
    connection = engine.connect()
    if not connection.scalar(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id}
    ):
        connection.close()
        return None
    try:
        with Session() as db:
            for stale in db.scalars(
                select(Run).where(Run.status == "running", Run.job_id == job_id)
            ):
                stale.status, stale.ended_at = "interrupted", now()
            run = Run(job_id=job_id, trigger=trigger, started_at=now(), logs=[])
            db.add(run)
            db.commit()
            run_id = run.id
    except Exception:
        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id})
        connection.close()
        raise

    def execute():
        """异常时保留已提交区间，清理互斥锁并记录安全摘要。"""
        try:
            collectors[job_id](run_id)
        except Exception:  # noqa: BLE001 — 后台边界必须落库并释放锁，不暴露源凭据
            logger.error("采集任务异常 run_id=%s；请检查数据库及数据源配置", run_id)
            with Session() as db:
                run = db.get(Run, run_id)
                run.status, run.ended_at = "failed", now()
                run.logs = [
                    *run.logs,
                    {
                        "status": "failed",
                        "message": "采集异常，请检查数据库或源数据格式",
                    },
                ]
                db.commit()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id}
            )
            connection.close()

    threading.Thread(target=execute, daemon=True).start()
    return run_id


def next_run(job):
    """按北京时间计算下一次调度，不表示源数据届时一定更新。"""
    if not job.enabled:
        return None
    current = now()
    hour, minute = map(int, job.time.split(":"))
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current or job.last_scheduled_date == current.date():
        target += timedelta(days=1)
    return target.isoformat()


def recover_interrupted(job_id=1):
    """仅在无活跃采集锁时，将重启遗留运行标为中断。"""
    lock_id = LOCK_ID + job_id - 1
    with engine.connect() as connection:
        if not connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_id}
        ):
            return
        try:
            with Session() as db:
                for run in db.scalars(
                    select(Run).where(Run.status == "running", Run.job_id == job_id)
                ):
                    run.status, run.ended_at = "interrupted", now()
                db.commit()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": lock_id}
            )


def scheduler(stop):
    """独立锁定四类任务配置，每天最多触发一次；仅行情需要凭据。"""
    while not stop.is_set():
        try:
            with Session() as db:
                task_ids = list(db.scalars(select(Job.id)))
            for job_id in task_ids:
                with Session() as db:
                    job = db.scalar(
                        select(Job).where(Job.id == job_id).with_for_update(key_share=True)
                    )
                    current = now()
                    configured = job_id in (2, 3, 4) or (
                        os.getenv("CHATBI_TOKEN") and os.getenv("CHATBI_ACCESS_CODE")
                    )
                    if not (
                        job.enabled
                        and configured
                        and current.strftime("%H:%M") >= job.time
                        and job.last_scheduled_date != current.date()
                    ):
                        continue
                    run_id = (
                        launch("scheduled")
                        if job_id == 1
                        else launch("scheduled", job_id=job_id)
                    )
                    if run_id is not None:
                        job.last_scheduled_date = current.date()
                        db.commit()
        except Exception:  # noqa: BLE001 — 调度边界记录安全摘要后等待下周期重试
            logger.error("调度检查失败；将在下一周期重试")
        stop.wait(30)
