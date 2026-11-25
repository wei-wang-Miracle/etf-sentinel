"""仅针对显式指定的本地测试库验证迁移后业务链路。"""

import os
import threading
import time
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import collection, jobs
from app.collection import TZ, collect, now
from app.db import Session, engine
from app.main import app
from app.models import BacktestSource, Candle, Instrument, Job, Run, Window

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test",
    reason="需要独立 etf_sentinel_test 本地数据库",
)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    """测试数据只进入独立测试库，重置后每例相互隔离。"""
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE candles, collection_windows, runs, instruments, jobs RESTART IDENTITY CASCADE"
            )
        )
        db.add_all(
            [
                Instrument(code="510500", start_date=date(2026, 5, 30)),
                Instrument(code="512100", enabled=False),
            ]
        )
        db.add(Job(id=1, enabled=False, time="01:00"))
        db.commit()
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 6, 3, tzinfo=TZ))


def run_id():
    """创建本次采集运行记录。"""
    with Session() as db:
        item = Run(trigger="manual", started_at=now(), logs=[])
        db.add(item)
        db.commit()
        return item.id


def source(code, start, end, price="1.5"):
    """生成请求区间内的源口径样本。"""
    return [
        {
            "STOCK_CODE": code,
            "STOCK_NAME": "测试标的",
            "TRADE_DATE": str(start),
            "OPEN_PRICE": 1,
            "HIGH_PRICE": 2,
            "LOW_PRICE": 0.5,
            "CLOSE_PRICE": price,
            "VOLUME": 5000000000,
            "AMOUNT": 7500000000,
        }
    ]


def test_idempotency_and_revision():
    first = run_id()
    collect(first, source)
    second = run_id()
    collect(second, lambda c, s, e: source(c, s, e, "1.6"))
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Candle)) == 2
        assert db.get(Candle, ("510500", date(2026, 6, 1))).close == Decimal("1.6")
        assert db.get(Run, second).status == "success"
        assert db.get(Instrument, "510500").name == "测试标的"
        assert (
            db.scalar(
                select(func.count()).select_from(Candle).where(Candle.code == "512100")
            )
            == 0
        )


def test_failed_month_retries_and_empty_window():
    def fail_old(code, start, end):
        if start.month == 5:
            raise ValueError("测试网络错误")
        return []

    first = run_id()
    collect(first, fail_old)
    with Session() as db:
        assert db.get(Run, first).status == "partial"
        assert db.get(Window, ("510500", date(2026, 5, 30))) is None
        assert db.get(Window, ("510500", date(2026, 6, 1))) is not None
    requests = []
    collect(run_id(), lambda c, s, e: requests.append((c, s, e)) or [])
    assert any(s.month == 5 for _, s, _ in requests)


def test_invalid_window_is_atomic():
    def invalid(code, start, end):
        values = source(code, start, end)
        return values + [{**values[0], "HIGH_PRICE": 0.1}]

    first = run_id()
    collect(first, invalid)
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Candle)) == 0
        assert db.scalar(select(func.count()).select_from(Window)) == 0
        assert db.get(Run, first).status == "partial"


def test_market_job_verifies_all_configured_equity_sources_independently():
    checked = []

    def fetch_equity(code):
        checked.append(code)
        if code == "512100":
            raise ValueError("权益来源暂不可用")
        return {
            "actions": {"dividends": [], "splits": []},
            "source_url": f"https://example.com/{code}",
            "source_html": "测试权益资料",
            "source_sha256": "f" * 64,
            "collected_at": now(),
        }

    run = run_id()
    collect(run, source, fetch_equity=fetch_equity)

    with Session() as db:
        result = db.get(Run, run)
        assert result.status == "partial"
        assert checked == ["510500", "512100"]
        assert db.scalar(select(func.count()).select_from(Candle)) == 2
        assert db.get(BacktestSource, "510500") is not None
        assert db.get(BacktestSource, "512100") is None
        equity_logs = [entry for entry in result.logs if entry.get("kind") == "equity"]
        assert [(entry["code"], entry["status"]) for entry in equity_logs] == [
            ("510500", "success"),
            ("512100", "failed"),
        ]


def test_config_and_local_candle_api():
    client = TestClient(app)
    assert (
        client.put(
            "/instruments/999999", json={"enabled": True, "start_date": "2020-01-01"}
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/instruments/510500", json={"enabled": True, "start_date": "2026-06-01"}
        ).status_code
        == 200
    )
    assert (
        client.put("/job", json={"enabled": True, "time": "25:99"}).status_code == 422
    )
    assert (
        client.put("/job", json={"enabled": False, "time": "02:30"}).status_code == 200
    )
    assert client.get("/job").json()["time"] == "02:30"
    collect(run_id(), source)
    response = client.get("/candles/510500?start=2026-06-01&end=2026-06-02")
    assert response.status_code == 200 and len(response.json()) == 1
    assert (
        client.get("/candles/510500?start=2026-06-03&end=2026-06-01").status_code == 422
    )
    assert client.get("/instruments").json()[0]["count"] == 1


def test_running_job_exclusion(monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking(run):
        entered.set()
        release.wait(5)
        finished.set()

    monkeypatch.setattr(jobs, "collect", blocking)
    first = jobs.launch()
    assert first is not None
    assert entered.wait(2)
    try:
        assert jobs.launch() is None
    finally:
        release.set()
    assert finished.wait(2)
    # 等待后台线程释放数据库连接，再开始后续测试。
    for _ in range(100):
        with engine.connect() as conn:
            if conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": jobs.LOCK_ID}
            ):
                conn.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": jobs.LOCK_ID}
                )
                break
        time.sleep(0.02)
    else:
        pytest.fail("任务未释放互斥锁")


def test_recovery_marks_stale_and_respects_active_lock(monkeypatch):
    stale = run_id()
    jobs.recover_interrupted()
    with Session() as db:
        assert db.get(Run, stale).status == "interrupted"
    active = run_id()
    with engine.connect() as conn:
        assert conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": jobs.LOCK_ID}
        )
        try:
            jobs.recover_interrupted()
            with Session() as db:
                assert db.get(Run, active).status == "running"
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": jobs.LOCK_ID})


def test_schedule_runs_once_per_local_day(monkeypatch):
    monkeypatch.setenv("CHATBI_TOKEN", "test")
    monkeypatch.setenv("CHATBI_ACCESS_CODE", "test")
    monkeypatch.setattr(jobs, "now", lambda: datetime(2026, 6, 3, 2, tzinfo=TZ))
    calls = []
    monkeypatch.setattr(jobs, "launch", lambda trigger: calls.append(trigger) or 1)

    class Stop:
        def is_set(self):
            return False

        def wait(self, _):
            raise StopIteration

    with Session() as db:
        db.get(Job, 1).enabled = True
        db.commit()
    for _ in range(2):
        with pytest.raises(StopIteration):
            jobs.scheduler(Stop())
    assert calls == ["scheduled"]
    with Session() as db:
        assert db.get(Job, 1).last_scheduled_date == date(2026, 6, 3)


def test_moving_start_backfills_older_dates():
    with Session() as db:
        db.get(Instrument, "510500").start_date = date(2026, 6, 1)
        db.commit()
    collect(run_id(), source)
    with Session() as db:
        db.get(Instrument, "510500").start_date = date(2026, 5, 30)
        db.commit()
    collect(run_id(), source)
    with Session() as db:
        assert db.get(Candle, ("510500", date(2026, 5, 30))) is not None


def test_incremental_window_uses_recent_overlap(monkeypatch):
    with Session() as db:
        db.get(Instrument, "510500").start_date = date(2026, 6, 1)
        db.commit()
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 6, 21, tzinfo=TZ))
    collect(run_id(), lambda c, s, e: [])
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 6, 22, tzinfo=TZ))
    calls = []
    collect(run_id(), lambda c, s, e: calls.append((s, e)) or [])
    assert calls == [(date(2026, 6, 13), date(2026, 6, 21))]


def test_failed_refresh_retries_after_overlap_expires(monkeypatch):
    """已有成功水位的复查失败，不能在退出七日窗口后被跳过。"""
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 6, 8, tzinfo=TZ))
    collect(run_id(), lambda c, s, e: [])

    def fail_may(code, start, end):
        if start.month == 5:
            raise ValueError("测试复查失败")
        return []

    collect(run_id(), fail_may)
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 6, 9, tzinfo=TZ))
    requests = []
    collect(run_id(), lambda c, s, e: requests.append((s, e)) or [])
    assert any(s.month == 5 for s, e in requests)


def test_database_semantic_names_and_comments():
    """数据库字段和注释必须与模型一致，外键复用相同语义名。"""
    from sqlalchemy import inspect

    from app.models import Base

    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        assert inspector.get_table_comment(table.name)["text"] == table.comment
        actual = {
            column["name"]: column for column in inspector.get_columns(table.name)
        }
        assert set(actual) == set(table.columns.keys())
        for column in table.columns:
            assert column.comment and actual[column.name]["comment"] == column.comment
        for foreign_key in inspector.get_foreign_keys(table.name):
            assert foreign_key["constrained_columns"] == foreign_key["referred_columns"]
