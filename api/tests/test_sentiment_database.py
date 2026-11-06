"""在独立测试库验证恐贪水位、幂等、失败隔离及本地查询。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import jobs
from app.collection import now
from app.db import Session
from app.main import app
from app.models import Job, Run, SentimentDaily
from app.sentiment import collect_sentiment

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


@pytest.fixture(autouse=True)
def reset():
    """清空专用测试库的数据，建立两个独立任务。"""
    with Session() as db:
        db.execute(text("TRUNCATE sentiment_categories, jobs RESTART IDENTITY CASCADE"))
        db.add_all([Job(id=1, enabled=False), Job(id=2, enabled=False, time="01:10")])
        db.commit()


def run_id(job_id=2):
    """创建指定任务的运行。"""
    with Session() as db:
        run = Run(job_id=job_id, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        return run.id


def source(calls, *, invalid=False, empty=False, new=False, revision=25):
    """模拟目录和历史序列，保留零分及旧历史供增量判定。"""

    def fetch(path="", params=None):
        if not path:
            return {
                "items": [
                    {
                        "key": key,
                        "name": key,
                        "date": "2026-11-05",
                        "value": 0,
                        "desc": "测试标签",
                    }
                    for key in (["gf", "qs"] if new else ["gf"])
                ]
            }
        calls.append(dict(params))
        rows = [
            {"date": "2021-11-08", "value": revision, "close": 100},
            {"date": "2026-11-02", "value": revision, "close": None},
            {"date": "2026-11-05", "value": 0, "close": 120},
        ]
        if invalid and params["key"] == "gf":
            rows.append({"date": "2026-11-06", "value": 101})
        return {
            "key": params["key"],
            "index_name": "测试指数",
            "series": [] if empty else rows,
        }

    return fetch


def test_initial_incremental_revision_and_new_category():
    """初次五年、后续一年，只修订交叠；新增类别仍首采五年。"""
    calls = []
    collect_sentiment(run_id(), source(calls))
    collect_sentiment(run_id(), source(calls, revision=30, new=True))
    assert calls == [
        {"key": "gf", "years": 5},
        {"key": "gf", "years": 1},
        {"key": "qs", "years": 5},
    ]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(SentimentDaily)) == 6
        assert db.get(
            SentimentDaily, ("gf", date(2021, 11, 8))
        ).fear_greed_score == Decimal(25)
        assert db.get(
            SentimentDaily, ("gf", date(2026, 11, 2))
        ).fear_greed_score == Decimal(30)
        assert db.get(SentimentDaily, ("gf", date(2026, 11, 5))).fear_greed_score == 0


def test_invalid_category_is_atomic_and_other_category_continues():
    """坏类别不推进水位，正常类别独立完成，失败类别下次仍五年。"""
    first = run_id()
    collect_sentiment(first, source([], invalid=True, new=True))
    with Session() as db:
        assert db.get(Run, first).status == "partial"
        assert db.get(SentimentDaily, ("gf", date(2026, 11, 5))) is None
        assert db.get(SentimentDaily, ("qs", date(2026, 11, 5))) is not None
    calls = []
    collect_sentiment(run_id(), source(calls))
    assert {"key": "gf", "years": 5} in calls


def test_empty_response_preserves_history():
    """空源响应报失败，不清空已存历史。"""
    collect_sentiment(run_id(), source([]))
    failed = run_id()
    collect_sentiment(failed, source([], empty=True))
    with Session() as db:
        assert db.get(Run, failed).status == "failed"
        assert db.scalar(select(func.count()).select_from(SentimentDaily)) == 3


def test_api_zero_snapshot_and_task_isolation():
    """本地接口区分零和缺失，任务配置和运行日志不混用。"""
    collect_sentiment(run_id(), source([]))
    client = TestClient(app)
    item = client.get("/sentiment/categories").json()[0]
    assert item["fear_greed_score"] == 0 and item["source_label"] == "测试标签"
    assert (
        client.get("/sentiment/series/gf?start=2026-11-01&end=2026-11-05").json()[0][
            "close_price"
        ]
        is None
    )
    assert (
        client.get("/sentiment/series/gf?start=2026-11-06&end=2026-11-05").status_code
        == 422
    )
    assert (
        client.get(
            "/sentiment/series/unknown?start=2026-11-01&end=2026-11-05"
        ).status_code
        == 404
    )
    assert (
        client.put(
            "/sentiment/job", json={"enabled": True, "time": "03:20"}
        ).status_code
        == 200
    )
    assert client.get("/sentiment/job").json()["time"] == "03:20"
    assert client.get("/job").json()["time"] == "01:00"
    assert len(client.get("/sentiment/job").json()["runs"]) == 1
    assert client.get("/job").json()["runs"] == []
    first, second = run_id(1), run_id(2)
    jobs.recover_interrupted(2)
    with Session() as db:
        assert db.get(Run, first).status == "running"
        assert db.get(Run, second).status == "interrupted"


def test_uncovered_history_gap_does_not_advance():
    """超出源窗口的断档必须失败并保留原水位。"""
    collect_sentiment(run_id(), source([]))
    with Session() as db:
        db.execute(
            text(
                "UPDATE sentiment_daily SET trade_date = '2010-01-01' WHERE category_key = 'gf' AND trade_date = '2026-11-05'"
            )
        )
        db.execute(text("DELETE FROM sentiment_daily WHERE trade_date != '2010-01-01'"))
        db.commit()
    calls = []
    failed = run_id()
    collect_sentiment(failed, source(calls))
    assert calls == [{"key": "gf", "years": 5}]
    with Session() as db:
        assert db.get(Run, failed).status == "failed"
        assert db.scalar(select(func.max(SentimentDaily.trade_date))) == date(
            2010, 1, 1
        )


def test_mismatched_snapshot_label_hidden():
    """快照与历史分数不同不能展示源标签。"""
    from app.models import SentimentCategory

    collect_sentiment(run_id(), source([]))
    with Session() as db:
        db.get(SentimentCategory, "gf").snapshot_score = 10
        db.commit()
    assert (
        TestClient(app).get("/sentiment/categories").json()[0]["source_label"] is None
    )


def test_independent_task_locks(monkeypatch):
    """同类禁止重入，两类可以独立运行且不会相互标记中断。"""
    import threading
    import time

    from app.db import engine

    entered = {key: threading.Event() for key in (1, 2)}
    release = threading.Event()

    def block(key):
        def execute(_):
            entered[key].set()
            release.wait(5)

        return execute

    monkeypatch.setattr(jobs, "collect", block(1))
    monkeypatch.setattr(jobs, "collect_sentiment", block(2))
    try:
        first = jobs.launch(job_id=1)
        second = jobs.launch(job_id=2)
        assert entered[1].wait(2) and entered[2].wait(2)
        assert jobs.launch(job_id=2) is None
        jobs.recover_interrupted(1)
        jobs.recover_interrupted(2)
        with Session() as db:
            assert db.get(Run, first).status == "running"
            assert db.get(Run, second).status == "running"
    finally:
        release.set()
        for key in (jobs.LOCK_ID, jobs.LOCK_ID + 1):
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
