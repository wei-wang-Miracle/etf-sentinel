"""独立测试库验证指数采集事务、修订证据与失败恢复。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.collection import now
from app.db import Session
from app.index_collection import collect_indices
from app.models import (
    IndexValuationDaily,
    IndexValuationRevision,
    IndexValuationSnapshot,
    Job,
    ResearchIndex,
    Run,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test",
    reason="需要独立etf_sentinel_test数据库",
)


@pytest.fixture(autouse=True)
def reset():
    with Session() as db:
        db.execute(
            text("TRUNCATE research_indices, runs, jobs RESTART IDENTITY CASCADE")
        )
        db.add(Job(id=4, enabled=False, time="01:30"))
        db.add(
            ResearchIndex(
                index_code="000905.SH",
                index_name="中证500",
                chatbi_code="000905",
                collection_enabled=True,
            )
        )
        db.commit()


def new_run():
    with Session() as db:
        run = Run(job_id=4, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        return run.id


def source(path="", params=None, value=10, omit=False):
    if not path:
        return {"rows": [{"code": "000905.SH", "update_time": "2026-11-05"}]}
    if path == "/detail":
        return {"header": {"code": params["code"]}, "update_time": "2026-11-05"}
    series = [{"date": "2026-11-04", "value": value}]
    if not omit:
        series.append({"date": "2026-11-05", "value": 20})
    return {"code": params["code"], "metric": params["metric"], "series": series}


def test_idempotency_revisions_and_source_deletion():
    collect_indices(new_run(), fetch=source, fetch_candles=lambda *args: [])
    with Session() as db:
        original = db.get(
            IndexValuationDaily, ("000905.SH", "pe", date(2026, 11, 4))
        ).collected_at
        assert db.scalar(select(func.count()).select_from(IndexValuationRevision)) == 10
    collect_indices(new_run(), fetch=source, fetch_candles=lambda *args: [])
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(IndexValuationSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(IndexValuationRevision)) == 10
        assert (
            db.get(
                IndexValuationDaily, ("000905.SH", "pe", date(2026, 11, 4))
            ).collected_at
            == original
        )
    collect_indices(
        new_run(),
        fetch=lambda p, q: source(p, q, value=11),
        fetch_candles=lambda *args: [],
    )
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(IndexValuationRevision)) == 15
        row = db.get(IndexValuationDaily, ("000905.SH", "pe", date(2026, 11, 4)))
        assert row.metric_value == Decimal(11)
    run_id = new_run()
    collect_indices(
        run_id,
        fetch=lambda p, q: source(p, q, omit=True),
        fetch_candles=lambda *args: [],
    )
    with Session() as db:
        assert db.get(Run, run_id).status == "failed"
        assert db.scalar(select(func.count()).select_from(IndexValuationDaily)) == 10
        assert (
            db.get(
                IndexValuationDaily, ("000905.SH", "pe", date(2026, 11, 4))
            ).metric_value
            == 11
        )


def test_single_metric_failure_does_not_block_others():
    def fetch(path, params):
        if path == "/history" and params["metric"] == "pb":
            raise ValueError("测试单指标失败")
        return source(path, params)

    run_id = new_run()
    collect_indices(run_id, fetch=fetch, fetch_candles=lambda *args: [])
    with Session() as db:
        assert db.get(Run, run_id).status == "partial"
        assert db.scalar(select(func.count()).select_from(IndexValuationDaily)) == 8


def test_local_api_rejects_unconfigured_index_and_preserves_window():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert (
        client.get(
            "/index-valuations/series/000680.SH?start=2020-01-01&end=2026-11-05"
        ).status_code
        == 404
    )
    collect_indices(new_run(), fetch=source, fetch_candles=lambda *args: [])
    base = "/index-valuations/series/000905.SH?metric=pe&end=2026-11-05&start="
    all_rows = client.get(base + "2026-11-01").json()
    subset = client.get(base + "2026-11-05").json()
    assert (
        subset["series"][0]["local_percentile"]
        == all_rows["series"][-1]["local_percentile"]
        == 50
    )
    assert client.get("/index-valuations/job").json()["source_configured"] is True
    assert client.get(base + "2027-01-01").status_code == 422


def test_schedule_job_lock_allows_run_foreign_key_insert(monkeypatch):
    """配置行互斥不能阻塞另一连接创建运行记录的外键检查。"""
    from app import jobs

    called = []
    monkeypatch.delenv("CHATBI_TOKEN", raising=False)
    monkeypatch.delenv("CHATBI_ACCESS_CODE", raising=False)
    with Session() as db:
        job = db.get(Job, 4)
        job.enabled, job.time = True, "00:00"
        db.commit()

    def launch(trigger, job_id):
        with Session() as db:
            db.execute(text("SET LOCAL lock_timeout = '300ms'"))
            run = Run(job_id=job_id, trigger=trigger, started_at=now(), logs=[])
            db.add(run)
            db.commit()
            called.append(run.id)
            return run.id

    class Stop:
        def is_set(self):
            return False

        def wait(self, _):
            raise StopIteration

    monkeypatch.setattr(jobs, "launch", launch)
    with pytest.raises(StopIteration):
        jobs.scheduler(Stop())
    assert len(called) == 1


def test_empty_historical_month_is_retried_and_recovers(monkeypatch):
    """有估值交易日却无行情的旧月不能形成永久成功水位。"""
    from datetime import datetime

    from app import index_collection
    from app.collection import TZ
    from app.models import IndexCandle, IndexCollectionWindow

    monkeypatch.setattr(
        index_collection, "now", lambda: datetime(2026, 12, 10, tzinfo=TZ)
    )
    collect_indices(new_run(), fetch=source, fetch_candles=lambda *args: [])
    with Session() as db:
        assert db.get(IndexCollectionWindow, ("000905.SH", date(2026, 11, 4))) is None
    calls = []

    def fetch(code, start, end):
        calls.append((start, end))
        return [
            candle(code, day)
            for day in (date(2026, 11, 4), date(2026, 11, 5))
            if start <= day <= end
        ]

    collect_indices(new_run(), fetch=source, fetch_candles=fetch)
    assert any(start.month == 11 for start, _ in calls)
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(IndexCandle)) == 2


def candle(code, day):
    return {
        "STOCK_CODE": code,
        "TRADE_DATE": str(day),
        "OPEN_PRICE": 10,
        "CLOSE_PRICE": 11,
        "HIGH_PRICE": 12,
        "LOW_PRICE": 9,
        "VOLUME": 100,
        "AMOUNT": 1000,
    }


def test_invalid_optional_candle_value_is_window_failure():
    def fetch(code, start, end):
        row = candle(code, start)
        row["CHANGE_PCT"] = "bad"
        return [row]

    run_id = new_run()
    collect_indices(run_id, fetch=source, fetch_candles=fetch)
    with Session() as db:
        assert db.get(Run, run_id).status == "partial"
        assert any(log["status"] == "failed" for log in db.get(Run, run_id).logs)


def test_natural_ten_year_head_expiry_keeps_old_data_and_accepts_new(monkeypatch):
    from datetime import datetime

    from app import index_collection
    from app.collection import TZ
    from app.index_collection import save_history

    run_id = new_run()
    with Session() as db:
        rows = [
            (date(2016, 11, 7), Decimal(10), "valid"),
            (date(2026, 11, 5), Decimal(20), "valid"),
        ]
        save_history(db, "000905.SH", "pe", rows, run_id)
        db.commit()
        monkeypatch.setattr(
            index_collection, "now", lambda: datetime(2026, 11, 8, tzinfo=TZ)
        )
        updated = [
            (date(2026, 11, 5), Decimal(20), "valid"),
            (date(2026, 11, 6), Decimal(21), "valid"),
        ]
        inserted, revised = save_history(db, "000905.SH", "pe", updated, run_id)
        assert (inserted, revised) == (1, 0)
        db.commit()
        assert (
            db.get(IndexValuationDaily, ("000905.SH", "pe", date(2016, 11, 7)))
            is not None
        )


def test_missing_credentials_still_collects_valuations(monkeypatch):
    """估值任务不能因指数行情凭据未配置而完全不执行。"""
    monkeypatch.delenv("CHATBI_TOKEN", raising=False)
    monkeypatch.delenv("CHATBI_ACCESS_CODE", raising=False)
    run_id = new_run()
    collect_indices(run_id, fetch=source)
    with Session() as db:
        assert db.get(Run, run_id).status == "partial"
        assert db.scalar(select(func.count()).select_from(IndexValuationDaily)) == 10
        assert any(
            "凭据" in log["message"] or "CHATBI_TOKEN" in log["message"]
            for log in db.get(Run, run_id).logs
        )


def test_task_four_reentry_and_recovery_are_isolated(monkeypatch):
    import threading
    import time

    from app import jobs
    from app.db import engine

    entered, release = threading.Event(), threading.Event()

    def block(_):
        entered.set()
        release.wait(5)

    monkeypatch.setattr(jobs, "collect_indices", block)
    try:
        run_id = jobs.launch(job_id=4)
        assert entered.wait(2)
        assert jobs.launch(job_id=4) is None
        jobs.recover_interrupted(4)
        jobs.recover_interrupted(1)
        with Session() as db:
            assert db.get(Run, run_id).status == "running"
    finally:
        release.set()
        for _ in range(100):
            with engine.connect() as connection:
                key = jobs.LOCK_ID + 3
                if connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                ):
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                    )
                    break
            time.sleep(0.02)
        else:
            pytest.fail("指数任务未释放独立锁")


def test_source_precision_is_not_rounded_before_percentile():
    """源ROE存在16位小数，不应先截断为同值再统计分位。"""
    from app.index_collection import save_history

    run_id = new_run()
    with Session() as db:
        rows = [
            (date(2026, 11, 4), Decimal("9.1234567890123456"), "valid"),
            (date(2026, 11, 5), Decimal("9.1234567890123457"), "valid"),
        ]
        save_history(db, "000905.SH", "roe", rows, run_id)
        db.commit()
        row = db.get(IndexValuationDaily, ("000905.SH", "roe", date(2026, 11, 4)))
        assert row.metric_value == rows[0][1]
