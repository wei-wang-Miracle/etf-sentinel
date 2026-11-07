"""独立测试库中的回测入库、数据拒绝与快照复算。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.collection import now
from app.db import Session
from app.main import app
from app.models import BacktestRun, BacktestSource, Candle, Instrument

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)
BODY = {
    "instrument_code": "510500",
    "strategy_key": "ma_trend",
    "parameters": {"window": 2},
    "start_date": "2026-06-03",
    "end_date": "2026-06-08",
    "initial_cash": "10000",
    "commission_rate": "0",
    "minimum_commission": "0",
    "slippage_bps": "0",
}


@pytest.fixture(autouse=True)
def sample():
    """准备连续交易日，不访问外网或真实业务库。"""
    with Session() as db:
        db.execute(text("TRUNCATE instruments RESTART IDENTITY CASCADE"))
        db.add(Instrument(code="510500", name="测试基金"))
        db.flush()
        for day, price in zip((1, 2, 3, 4, 5, 8), (10, 12, 11, 9, 11, 13)):
            db.add(
                Candle(
                    code="510500",
                    date=date(2026, 6, day),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    adjusted_close=price,
                    volume=10000,
                    amount=100000,
                    collected_at=now(),
                )
            )
        db.add(
            BacktestSource(
                instrument_code="510500",
                source_url="https://example.com/510500",
                checked_through_date=date(2026, 6, 8),
                collected_at=now(),
                source_sha256="a" * 64,
                source_html="测试证据",
                corporate_actions={"dividends": [], "splits": []},
            )
        )
        db.commit()


def test_snapshot_survives_market_revision():
    response = client.post("/backtests", json=BODY)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["result"]["strategy"]["trades"][0]["signal_date"] == "2026-06-02"
    with Session() as db:
        row = db.get(Candle, ("510500", date(2026, 6, 8)))
        row.close = row.adjusted_close = Decimal(14)
        row.high = Decimal(15)
        db.commit()
    assert client.post(f"/backtests/{saved['id']}/verify").json()["identical"]
    assert client.get(f"/backtests/{saved['id']}").json() == saved
    new = client.post("/backtests", json=BODY).json()
    assert new["input_sha256"] != saved["input_sha256"]
    assert new["result"] != saved["result"]
    assert len(client.get("/backtests").json()) == 2


def test_missing_source_gap_and_warmup_rejected():
    assert (
        client.post(
            "/backtests", json={**BODY, "parameters": {"window": 10}}
        ).status_code
        == 422
    )
    with Session() as db:
        db.delete(db.get(Candle, ("510500", date(2026, 6, 4))))
        db.commit()
    response = client.post("/backtests", json=BODY)
    assert response.status_code == 422 and "缺少交易日" in response.text
    with Session() as db:
        db.delete(db.get(BacktestSource, "510500"))
        db.commit()
    assert client.post("/backtests", json=BODY).status_code == 422
    with Session() as db:
        assert not db.scalars(select(BacktestRun)).all()


def test_request_boundaries_and_catalog():
    catalog = client.get("/backtests/catalog").json()
    assert catalog["strategies"][0]["key"] == "ma_trend"
    assert catalog["instruments"][0]["count"] == 6
    for patch in (
        {"instrument_code": "非代码"},
        {"parameters": {"window": 1}},
        {"parameters": {"window": "60"}},
        {"parameters": {"window": 60.5}},
        {"parameters": {"window": 2, "unknown": 3}},
        {"initial_cash": "NaN"},
        {"end_date": "2027-01-01"},
        {"start_date": "2026-06-09"},
        {"commission_rate": "-1"},
        {"strategy_key": "unknown"},
    ):
        assert client.post("/backtests", json={**BODY, **patch}).status_code == 422


def test_source_refresh_failure_keeps_previous_source(monkeypatch):
    """两只中任一源失败不能留下半批更新。"""
    from app import backtest_routes

    def fail_second(code):
        if code == "512100":
            raise ValueError("测试源失败")
        return {
            "actions": {"dividends": [], "splits": []},
            "source_url": "https://example.com/new",
            "source_html": "新资料",
            "source_sha256": "b" * 64,
            "collected_at": now(),
        }

    with Session() as db:
        db.add(Instrument(code="512100", name="第二只测试ETF"))
        db.commit()
    monkeypatch.setattr(backtest_routes, "fetch_actions", fail_second)
    assert client.post("/backtests/sources/refresh").status_code == 502
    with Session() as db:
        assert db.get(BacktestSource, "510500").source_sha256 == "a" * 64


def test_snapshot_version_and_digest_guards():
    """不能把不兼容或被改写输入的复算标记为一致。"""
    run = client.post("/backtests", json=BODY).json()
    with Session() as db:
        item = db.get(BacktestRun, run["id"])
        original = item.input_snapshot
        item.input_snapshot = {**original, "engine_version": "unknown"}
        db.commit()
    assert client.post(f"/backtests/{run['id']}/verify").status_code == 409
    with Session() as db:
        db.get(BacktestRun, run["id"]).input_snapshot = {
            **original,
            "data_version": "tampered",
        }
        db.commit()
    assert client.post(f"/backtests/{run['id']}/verify").status_code == 409
    with Session() as db:
        db.get(BacktestRun, run["id"]).input_snapshot = {
            **original,
            "settings": {**original["settings"], "initial_cash": "20000"},
        }
        db.commit()
    response = client.post(f"/backtests/{run['id']}/verify")
    assert response.status_code == 409 and "摘要" in response.text
