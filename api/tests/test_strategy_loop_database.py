"""独立测试库验证研究冻结、盘前时点和人工成交关联。"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_research_database import sample  # noqa: F401

from app.collection import now
from app.db import Session
from app.main import app
from app.models import AccountHoldingSnapshot, BacktestRun, Candle

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)
REQUEST = {
    "development_start": "2026-05-06",
    "development_end": "2026-05-29",
    "validation_start": "2026-06-01",
    "validation_end": "2026-06-30",
}


def batch():
    """运行固定研究，不允许调用方偷换研究本金或候选范围。"""
    response = client.post("/strategy-lab/batches", json=REQUEST)
    assert response.status_code == 200, response.text
    return response.json()


def test_batch_freezes_holdings_all_candidates_cash_and_replays():
    result = batch()
    assert result["input"]["initial_cash_per_etf"] == "50000"
    assert result["input"]["instruments"][0]["instrument_code"] == "159205"
    for period in ("development", "validation"):
        item = result["result"]["instruments"][0]["periods"][period]
        assert item["status"] == "available"
        assert len(item["tracks"]) == 5
        assert item["tracks"][-1]["same_exposure_benchmark"] is not None
    with Session() as db:
        runs = list(db.scalars(select(BacktestRun)))
        for run in runs:
            assert client.post(f"/backtests/{run.backtest_run_id}/verify").json()[
                "identical"
            ]
        db.get(
            AccountHoldingSnapshot, (1, date(2026, 6, 30), "159205")
        ).current_amount = 2000
        db.commit()
    assert client.get(f"/strategy-lab/batches/{result['id']}").json() == result
    assert (
        client.post(
            "/strategy-lab/batches", json={**REQUEST, "initial_cash": 100}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/strategy-lab/batches", json={**REQUEST, "validation_start": "2026-05-29"}
        ).status_code
        == 422
    )


def test_missing_data_keeps_failed_instrument_and_blocks_portfolio():
    with Session() as db:
        db.query(Candle).filter(Candle.date == date(2026, 6, 10)).delete()
        db.commit()
    result = batch()
    assert (
        result["result"]["instruments"][0]["periods"]["validation"]["status"]
        == "blocked"
    )
    assert result["result"]["portfolio"]["validation"]["status"] == "blocked"


def observe(batch_id, candidate="ma20"):
    """人工采用某个研究候选，返回冻结规则版本。"""
    response = client.post(
        "/strategy-lab/observations",
        json={
            "research_batch_id": batch_id,
            "instrument_code": "159205",
            "candidate_key": candidate,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def clock_at(monkeypatch, day="2026-07-01", hour=8):
    """统一冻结服务时钟和源采集时刻，避免测试偷用未来采集数据。"""
    from app import strategy_lab

    stamp = datetime.fromisoformat(day).replace(
        hour=hour, tzinfo=ZoneInfo("Asia/Shanghai")
    )
    monkeypatch.setattr(strategy_lab, "now", lambda: stamp)
    with Session() as db:
        from app.models import AccountSyncRun, BacktestSource

        for model in (Candle, AccountHoldingSnapshot, BacktestSource):
            for row in db.scalars(select(model)):
                row.collected_at = stamp.replace(hour=1)
        for row in db.scalars(select(AccountSyncRun)):
            row.started_at = row.ended_at = stamp.replace(hour=1)
        db.commit()
    return stamp


def test_signals_are_preopen_idempotent_and_immutable(monkeypatch):
    research = batch()
    clock_at(monkeypatch)
    version = observe(research["id"])
    first = client.post("/strategy-lab/signals/generate").json()
    assert len(first["created"]) == 1, first
    signal = first["created"][0]
    assert signal["execution_date"] == "2026-07-01"
    assert signal["data_cutoff"] == "2026-06-30"
    assert signal["plan"]["actual_quantity"] == "1000.0000"
    assert signal["plan"]["target_quantity"] == 0
    again = client.post("/strategy-lab/signals/generate").json()
    assert len(again["created"]) == 0
    assert again["existing"][0]["id"] == signal["id"]
    assert (
        client.post(f"/strategy-lab/observations/{version['id']}/pause").status_code
        == 200
    )
    assert client.get("/strategy-lab/signals").json()[0]["plan"] == signal["plan"]


def test_late_or_stale_data_never_backfills_signal(monkeypatch):
    research = batch()
    clock_at(monkeypatch)
    observe(research["id"])
    clock_at(monkeypatch, hour=10)
    blocked = client.post("/strategy-lab/signals/generate").json()
    assert blocked["created"] == []
    assert blocked["blocked"]
    clock_at(monkeypatch, day="2026-07-02")
    assert client.post("/strategy-lab/signals/generate").json()["created"] == []


def test_execution_needs_confirmed_date_unique_link_and_revision_tracking(monkeypatch):
    from app.models import AccountEntrust

    research = batch()
    clock_at(monkeypatch)
    observe(research["id"])
    signal = client.post("/strategy-lab/signals/generate").json()["created"][0]
    with Session() as db:
        db.add(
            AccountEntrust(
                account_id=1,
                instrument_code="159205",
                curr_date=date(2026, 7, 1),
                entrust_no="sell-1",
                entrust_side="2",
                business_amount=500,
                business_price=10,
                business_balance=5000,
                clear_balance=4999,
                fee_amount=1,
                data_date=date(2026, 7, 1),
                collected_at=now(),
            )
        )
        db.commit()
    clock_at(monkeypatch, hour=10)
    payload = {
        "curr_date": "2026-07-01",
        "entrust_no": "sell-1",
        "confirmed_trade_date": "2026-07-01",
        "confirmation_note": "已核对券商当日成交明细",
        "confirm_plan_preceded_trade": True,
    }
    assert (
        client.post(
            f"/strategy-lab/signals/{signal['id']}/link",
            json={**payload, "confirm_plan_preceded_trade": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal['id']}/link",
            json={**payload, "confirmed_trade_date": "2026-06-30"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal['id']}/link", json=payload
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal['id']}/link", json=payload
        ).status_code
        == 409
    )
    item = client.get("/strategy-lab/signals").json()[0]
    assert item["execution"]["status"] == "partial"
    with Session() as db:
        db.get(AccountEntrust, (1, date(2026, 7, 1), "sell-1")).business_amount = 1200
        db.commit()
    item = client.get("/strategy-lab/signals").json()[0]
    assert item["execution"]["status"] == "excess"
    assert item["execution"]["links"][0]["source_revised"]


def test_unchanged_holding_regime_does_not_rebalance_each_day(monkeypatch):
    """满仓之后参考价格变化不产生额外补减仓，半资金储备不能被动用于补仓。"""
    from app.models import BacktestSource

    research = batch()
    clock_at(monkeypatch)
    observe(research["id"], "confirm_half")
    # 测试使用持有规则，隔离价格波动与空满状态变化。
    with Session() as db:
        from app.models import StrategyObservation

        row = db.scalar(
            select(StrategyObservation).order_by(
                StrategyObservation.observation_id.desc()
            )
        )
        row.rule_snapshot = {
            **row.rule_snapshot,
            "strategy_key": "hold",
            "strategy_version": "1.0",
            "parameters": {},
        }
        db.commit()
    signal = client.post("/strategy-lab/signals/generate").json()["created"][0]
    quantity = signal["plan"]["target_quantity"]
    with Session() as db:
        db.add(
            Candle(
                code="159205",
                date=date(2026, 7, 1),
                open=10,
                high=13,
                low=9,
                close=12,
                adjusted_close=12,
                volume=10000,
                amount=100000,
                collected_at=now(),
            )
        )
        db.add(
            AccountHoldingSnapshot(
                account_id=1,
                instrument_code="159205",
                data_date=date(2026, 7, 1),
                current_amount=quantity,
                enable_amount=quantity,
                collected_at=now(),
            )
        )
        db.get(BacktestSource, "159205").checked_through_date = date(2026, 7, 1)
        db.commit()
    clock_at(monkeypatch, day="2026-07-02")
    second = client.post("/strategy-lab/signals/generate").json()["created"][0]
    assert second["plan"]["target_quantity"] == quantity
    assert second["plan"]["action"] == "hold"


def test_request_waiting_across_open_cannot_backdate_plan(monkeypatch):
    """请求在盘前开始，不代表行锁等待或计算结束后仍可生成当日计划。"""
    from app import strategy_lab

    research = batch()
    before = clock_at(monkeypatch).replace(hour=9, minute=29)
    observe(research["id"], "hold")
    times = iter([before, before.replace(minute=31)])
    monkeypatch.setattr(
        strategy_lab, "now", lambda: next(times, before.replace(minute=31))
    )
    result = client.post("/strategy-lab/signals/generate").json()
    assert result["created"] == []
    assert result["blocked"]


def test_invalid_market_data_blocks_factors_instead_of_fabricating_them():
    """展示因子也须校验本地价格，损坏数据不能让目录接口异常或生成数值。"""
    with Session() as db:
        db.get(Candle, ("159205", date(2026, 6, 1))).close = 0
        db.commit()
    response = TestClient(app, raise_server_exceptions=False).get(
        "/strategy-lab/catalog"
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["factors"] is None
    assert item["factor_warning"]


def test_calendar_outside_supported_range_is_input_error():
    response = TestClient(app, raise_server_exceptions=False).post(
        "/strategy-lab/batches", json={**REQUEST, "development_start": "1900-01-01"}
    )
    assert response.status_code == 422
