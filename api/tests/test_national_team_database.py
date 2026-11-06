"""独立数据库验证国家队比例幂等修订、失败隔离和日K对照。"""

import os
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import jobs
from app.collection import now
from app.db import Session
from app.main import app
from app.models import Job, NationalTeamDaily, NationalTeamInstrument, Run
from app.national_team import ESTIMATION_START, INSTRUMENT_CODES, collect_national_team

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


@pytest.fixture(autouse=True)
def reset():
    """仅清理专用测试库，建立三个独立任务。"""
    with Session() as db:
        db.execute(
            text("TRUNCATE national_team_instruments, jobs RESTART IDENTITY CASCADE")
        )
        db.add_all(
            [Job(id=i, enabled=False, time=f"01:{(i - 1) * 10:02}") for i in (1, 2, 3)]
        )
        db.commit()


def run_id():
    """创建国家队采集运行。"""
    with Session() as db:
        run = Run(job_id=3, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        return run.id


def source(calls, *, revision=10, bad=False, missing=False, truncated=False):
    """十八只固定基准样例，含零比例及可修订旧历史。"""

    def fetch(params):
        calls.append(params)
        items = []
        for code in INSTRUMENT_CODES:
            if missing and code == "510300":
                continue
            points = [
                {"date": "2026-01-05", "fe": 100, "nat_pct": revision},
                {"date": "2026-11-05", "fe": 100, "nat_pct": 0},
            ]
            if bad and code == "510300":
                points[0]["nat_pct"] = -1
            if truncated:
                points.pop()
            items.append(
                {
                    "code": code,
                    "name": code,
                    "index": "测试指数",
                    "hold_pct": 50,
                    "points": deepcopy(points),
                }
            )
        return {"code": 0, "data": {**params, "etfs": items}}

    return fetch


def test_repeat_is_no_write_and_old_history_revision_is_updated():
    """重复采集不改变记录时间，七日之外的旧历史修订仍更新。"""
    calls = []
    collect_national_team(run_id(), source(calls))
    with Session() as db:
        row = db.get(NationalTeamDaily, ("510300", date(2026, 1, 5)))
        timestamp = row.collected_at
    second = run_id()
    collect_national_team(second, source(calls))
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(NationalTeamDaily)) == 36
        assert (
            db.get(NationalTeamDaily, ("510300", date(2026, 1, 5))).collected_at
            == timestamp
        )
        assert sum(e["count"] for e in db.get(Run, second).logs) == 0
    collect_national_team(run_id(), source(calls, revision=20))
    with Session() as db:
        assert db.get(
            NationalTeamDaily, ("510300", date(2026, 1, 5))
        ).estimated_holding_pct == Decimal(20)
    assert all(c["start"] == str(ESTIMATION_START) for c in calls)


def test_bad_etf_is_atomic_other_seventeen_succeed_and_retry_recovers():
    """单只坏数据不影响其余十七只，下次继续采集。"""
    first = run_id()
    collect_national_team(first, source([], bad=True))
    with Session() as db:
        assert db.get(Run, first).status == "partial"
        assert db.scalar(select(func.count()).select_from(NationalTeamDaily)) == 34
    collect_national_team(run_id(), source([]))
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(NationalTeamDaily)) == 36


def test_missing_directory_and_truncated_history_preserve_existing_records():
    """源缺基金、缺历史日期时不删除旧记录，不冒充成功。"""
    collect_national_team(run_id(), source([]))
    missing = run_id()
    collect_national_team(missing, source([], missing=True))
    with Session() as db:
        assert db.get(Run, missing).status == "partial"
        assert not db.get(NationalTeamInstrument, "510300").source_available
    failed = run_id()
    collect_national_team(failed, source([], truncated=True))
    with Session() as db:
        assert db.get(Run, failed).status == "failed"
        assert db.scalar(select(func.count()).select_from(NationalTeamDaily)) == 36


def test_local_api_dates_missing_candles_and_task_isolation():
    """本地接口保持原比例，缺日K为空，任务3独立配置和日志。"""
    collect_national_team(run_id(), source([]))
    client = TestClient(app)
    directory = client.get("/national-team/instruments").json()
    assert len(directory) == 18
    assert directory[0]["estimated_holding_pct"] == 0
    result = client.get(
        "/national-team/series/510300?start=2026-11-01&end=2026-11-06"
    ).json()
    assert (
        len(result["holdings"]) == 1
        and result["holdings"][0]["estimated_holding_pct"] == 0
    )
    assert result["candles"] == []
    assert result["estimation_start_date"] == "2026-01-01"
    assert (
        client.get(
            "/national-team/series/999999?start=2026-01-01&end=2026-11-06"
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/national-team/series/510300?start=2026-11-06&end=2026-01-01"
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/national-team/job", json={"enabled": True, "time": "02:30"}
        ).status_code
        == 200
    )
    assert client.get("/national-team/job").json()["time"] == "02:30"
    assert len(client.get("/national-team/job").json()["runs"]) == 1
    assert client.get("/sentiment/job").json()["runs"] == []
    assert client.get("/job").json()["time"] == "01:00"


def test_independent_task_locks(monkeypatch):
    """同类禁止重入，三类可以独立运行且不会相互标记中断。"""
    import threading
    import time

    from app.db import engine

    entered = {key: threading.Event() for key in (1, 2, 3)}
    release = threading.Event()

    def block(key):
        def execute(_):
            entered[key].set()
            release.wait(5)

        return execute

    monkeypatch.setattr(jobs, "collect", block(1))
    monkeypatch.setattr(jobs, "collect_sentiment", block(2))
    monkeypatch.setattr(jobs, "collect_national_team", block(3))
    try:
        first = jobs.launch(job_id=1)
        second = jobs.launch(job_id=2)
        third = jobs.launch(job_id=3)
        assert entered[1].wait(2) and entered[2].wait(2)
        assert entered[3].wait(2)
        assert jobs.launch(job_id=3) is None
        assert jobs.launch(job_id=2) is None
        jobs.recover_interrupted(1)
        jobs.recover_interrupted(2)
        jobs.recover_interrupted(3)
        with Session() as db:
            assert db.get(Run, first).status == "running"
            assert db.get(Run, second).status == "running"
            assert db.get(Run, third).status == "running"
    finally:
        release.set()
        for key in (jobs.LOCK_ID, jobs.LOCK_ID + 1, jobs.LOCK_ID + 2):
            for _ in range(100):
                with engine.connect() as connection:
                    if connection.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                    ):
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                        )
                        break
                time.sleep(0.02)
            else:
                pytest.fail("后台任务未释放锁")
