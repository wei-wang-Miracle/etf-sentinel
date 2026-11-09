"""三期功能的独立测试库集成，不访问外源和真实账户。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.backtest_data import trading_days
from app.collection import now
from app.db import Session
from app.main import app
from app.models import (
    Account,
    AccountEntrust,
    AccountHoldingSnapshot,
    AccountSyncRun,
    BacktestRun,
    BacktestSource,
    Candle,
    Instrument,
    InstrumentIndexLink,
    ResearchIndex,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)


@pytest.fixture(autouse=True)
def sample():
    """配置新ETF和足够预热，证明资格不依赖旧白名单。"""
    days, _ = trading_days("2025-01-17", "2026-06-30")
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE instruments, accounts, research_indices RESTART IDENTITY CASCADE"
            )
        )
        db.add(Instrument(code="159205", name="测试ETF"))
        db.add(
            Account(
                account_id=1, account_name="测试", base_currency="CNY", created_at=now()
            )
        )
        db.add(
            ResearchIndex(
                index_code="000001.SH", index_name="测试指数", chatbi_code="000001"
            )
        )
        db.flush()
        db.add(
            InstrumentIndexLink(
                instrument_code="159205",
                index_code="000001.SH",
                mapping_evidence="测试映射",
                verified_date=date(2026, 6, 30),
            )
        )
        for day in days:
            db.add(
                Candle(
                    code="159205",
                    date=date.fromisoformat(day),
                    open=10,
                    high=11,
                    low=9,
                    close=10,
                    adjusted_close=10,
                    volume=10000,
                    amount=100000,
                    collected_at=now(),
                )
            )
        db.add(
            BacktestSource(
                instrument_code="159205",
                source_url="https://example.com",
                checked_through_date=date(2026, 6, 30),
                collected_at=now(),
                source_sha256="a" * 64,
                source_html="明确无事件测试",
                corporate_actions={"dividends": [], "splits": []},
            )
        )
        db.add(
            AccountSyncRun(
                account_id=1,
                status="success",
                range_start=date(2025, 1, 20),
                range_end=date(2026, 6, 30),
                started_at=now(),
                ended_at=now(),
            )
        )
        db.add(
            AccountEntrust(
                account_id=1,
                instrument_code="159205",
                curr_date=date(2026, 6, 1),
                entrust_no="1",
                entrust_side="1",
                business_amount=1000,
                business_price=10,
                business_balance=10000,
                clear_balance=10001,
                fee_amount=1,
                data_date=date(2026, 6, 1),
                collected_at=now(),
            )
        )
        db.add(
            AccountHoldingSnapshot(
                account_id=1,
                instrument_code="159205",
                data_date=date(2026, 6, 30),
                current_amount=1000,
                enable_amount=1000,
                collected_at=now(),
            )
        )
        db.commit()


def test_actual_requires_explicit_evidence_and_uses_full_history():
    path = "/account/review/159205?start=2026-06-02&end=2026-06-30"
    blocked = client.get(path).json()
    assert blocked["actual"]["status"] == "blocked"
    result = client.get(
        path + "&confirm_zero_opening=true&confirm_trade_dates=true"
    ).json()
    assert result["actual"]["status"] == "available"
    assert Decimal(result["actual"]["initial_asset"]) == 10000
    assert Decimal(result["actual"]["net_pnl"]) == 0
    assert result["actual"]["daily"][0]["quantity"] == "1000.0000"
    assert result["quality"]["quantity_delta"] == "0.0000"


def test_partial_sync_blocks_until_whole_failed_interval_is_repaired():
    with Session() as db:
        db.add(
            AccountSyncRun(
                account_id=1,
                status="partial",
                range_start=date(2026, 6, 1),
                range_end=date(2026, 6, 10),
                started_at=now(),
                ended_at=now(),
            )
        )
        db.commit()
    path = "/account/review/159205?start=2026-06-02&end=2026-06-30&confirm_zero_opening=true&confirm_trade_dates=true"
    assert client.get(path).json()["actual"]["status"] == "blocked"
    with Session() as db:
        db.add(
            AccountSyncRun(
                account_id=1,
                status="success",
                range_start=date(2026, 6, 1),
                range_end=date(2026, 6, 10),
                started_at=now(),
                ended_at=now(),
            )
        )
        db.commit()
    assert client.get(path).json()["actual"]["status"] == "available"


def test_research_same_interval_and_snapshot_replay():
    response = client.post("/account/research/159205?start=2026-06-01&end=2026-06-30")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["tracks"]) == 4
    assert (
        len(
            {
                (r["daily"][0]["trade_date"], r["daily"][-1]["trade_date"])
                for r in data["tracks"]
            }
        )
        == 1
    )
    assert data["settings"]["minimum_commission"] == "0"
    from app.backtest import run_backtest
    from app.backtest_routes import digest

    for run in data["experiment_ids"]:
        with Session() as db:
            item = db.get(BacktestRun, run)
            snapshot = item.input_snapshot
            assert digest(snapshot) == item.input_sha256
            assert (
                run_backtest(
                    snapshot["rows"],
                    snapshot["actions"]["dividends"],
                    snapshot["settings"],
                )
                == item.result_snapshot
            )


def test_baselines_are_atomic_if_short_run_fails(monkeypatch):
    from app import review_routes

    original = review_routes.execute_backtest

    def fail_second(body, db):
        if body.parameters["window"] == 20:
            from fastapi import HTTPException

            raise HTTPException(422, "测试失败")
        return original(body, db)

    monkeypatch.setattr(review_routes, "execute_backtest", fail_second)
    assert (
        client.post(
            "/account/research/159205?start=2026-06-01&end=2026-06-30"
        ).status_code
        == 422
    )
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(BacktestRun)) == 0


def test_object_mappings_and_no_index_holdings_aggregation():
    etf = client.get("/research/object?object_type=etf&code=159205").json()
    assert etf["linked"]["index_code"] == "000001.SH"
    assert etf["summary"]["investment_status"] == "holding"
    index = client.get("/research/object?object_type=index&code=000001.SH").json()
    assert index["linked"]["instruments"][0]["code"] == "159205"
    assert index["summary"]["national_team"]["ratio"] is None
    assert index["object"]["type"] == "etf"
    assert index["summary"]["investment_status"] == "holding"
    assert client.get("/research/object?object_type=etf&code=999999").status_code == 404


def test_compare_future_invariance_and_units():
    path = "/research/compare?dimension=trend&start=2026-06-01&end=2026-06-30"
    before = client.get(path).json()
    with Session() as db:
        db.add(
            Candle(
                code="159205",
                date=date(2026, 7, 1),
                open=100,
                high=100,
                low=100,
                close=100,
                adjusted_close=100,
                volume=100,
                amount=10000,
                collected_at=now(),
            )
        )
        db.commit()
    assert client.get(path).json() == before
    assert before["items"][0]["rank"] == 1
    assert before["meta"]["annualization_factor"] == 252
    assert (
        client.get(
            "/research/compare?dimension=trend&start=2026-06-01&end=2026-06-30&codes=1,2,3,4,5,6,7"
        ).status_code
        == 422
    )


def test_research_query_validation_does_not_become_internal_error():
    assert (
        client.post(
            "/account/research/invalid?start=2026-06-01&end=2026-06-30"
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/account/research/159205?start=2026-06-01&end=2026-06-30&initial_cash=1000.123"
        ).status_code
        == 422
    )
