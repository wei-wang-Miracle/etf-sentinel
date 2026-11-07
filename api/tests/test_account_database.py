"""独立测试库验证账户同步幂等、过滤、费用和查询接口。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.account_sync import AccountConfig, sync_account
from app.collection import now
from app.db import Session
from app.main import app
from app.models import (
    AccountEntrust,
    AccountHoldingSnapshot,
    AccountSyncRun,
    Candle,
    Instrument,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)


def account_config():
    return AccountConfig(
        url="https://example.test/api",
        access_code="test-access",
        token="test-token",
        fund_account="12345678",
        start_date=date(2026, 11, 1),
        account_id=1,
    )


def holding_row(price="7.0"):
    return {
        "STOCK_CODE": "510500",
        "DATA_DATE": "20261105",
        "CURRENT_AMOUNT": 1000,
        "ENABLE_AMOUNT": 1000,
        "FROZEN_AMOUNT": 0,
        "UNCOME_BUY_AMOUNT": 0,
        "UNCOME_SELL_AMOUNT": 0,
        "COST_PRICE": price,
        "SUM_BUY_AMOUNT": 1000,
        "SUM_BUY_BALANCE": 7000,
        "SUM_SELL_AMOUNT": 0,
        "SUM_SELL_BALANCE": 0,
        "ETL_TIME": "2026-11-05 22:58:48",
        "FUND_ACCOUNT": "secret",
    }


def entrust_row(price="7.0", clear="7007.0"):
    return {
        "CURR_DATE": "20261103",
        "CURR_TIME": 94441116,
        "INIT_DATE": "20261103",
        "ENTRUST_NO": 1001,
        "ORDER_ID": 1001,
        "STOCK_CODE": "510500",
        "ENTRUST_BS": "1",
        "ENTRUST_AMOUNT": 1000,
        "ENTRUST_PRICE": price,
        "ENTRUST_TYPE": "0",
        "BUSINESS_AMOUNT": 1000,
        "BUSINESS_PRICE": price,
        "BUSINESS_BALANCE": 7000,
        "CLEAR_BALANCE": clear,
        "WITHDRAW_AMOUNT": 0,
        "ENTRUST_STATUS": "8",
        "FARE_KIND": 1001,
        "DATA_DATE": "20261103",
        "ETL_TIME": "2026-11-03 21:00:00",
        "OP_STATION": "secret-device",
    }


@pytest.fixture(autouse=True)
def reset():
    """只清理独立测试库中的账户和行情表。"""
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE account_entrusts, account_holdings_snapshots, "
                "account_sync_runs, accounts, instruments RESTART IDENTITY CASCADE"
            )
        )
        db.add_all(
            [
                Instrument(code="510500", name="测试基金"),
                Instrument(code="159205", name="测试基金二"),
            ]
        )
        db.flush()
        db.add(
            Candle(
                code="510500",
                date=date(2026, 11, 5),
                open=8,
                high=8.2,
                low=7.9,
                close=8,
                adjusted_close=8,
                volume=1000,
                amount=8000,
                collected_at=now(),
            )
        )
        db.commit()


def test_sync_filters_and_is_idempotent():
    def holdings(_config):
        return [holding_row(), {**holding_row(), "STOCK_CODE": "159755"}]

    def entrusts(_config, start, end):
        return [
            entrust_row(),
            {**entrust_row(), "ENTRUST_NO": 2002, "STOCK_CODE": "159755"},
        ]

    first = sync_account(
        config=account_config(),
        fetch_holdings_fn=holdings,
        fetch_entrust_fn=entrusts,
        today=date(2026, 11, 5),
    )
    assert first["status"] == "success"
    assert first["stored_count"] == 2
    assert first["skipped_count"] == 2
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(AccountHoldingSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(AccountEntrust)) == 1
        assert db.scalar(select(func.count()).select_from(AccountSyncRun)) == 1
        row = db.get(AccountEntrust, (1, date(2026, 11, 3), "1001"))
        assert row.fee_amount == Decimal("7.0000")

    second = sync_account(
        config=account_config(),
        fetch_holdings_fn=lambda _config: [holding_row("7.1")],
        fetch_entrust_fn=lambda _config, start, end: [entrust_row("7.1", "7009.0")],
        today=date(2026, 11, 5),
    )
    assert second["status"] == "success"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(AccountHoldingSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(AccountEntrust)) == 1
        row = db.get(AccountEntrust, (1, date(2026, 11, 3), "1001"))
        assert row.fee_amount == Decimal("9.0000")
        assert row.business_price == Decimal("7.10000000")


def test_holdings_and_entrusts_routes():
    sync_account(
        config=account_config(),
        fetch_holdings_fn=lambda _config: [holding_row()],
        fetch_entrust_fn=lambda _config, start, end: [entrust_row()],
        today=date(2026, 11, 5),
    )
    holdings = client.get("/account/holdings")
    assert holdings.status_code == 200
    body = holdings.json()
    assert body["as_of"] == "2026-11-05"
    assert body["summary"]["configured_only"] is True
    assert body["items"][0]["instrument_code"] == "510500"
    assert body["items"][0]["market_value"] == 8000
    assert body["items"][0]["unrealized_pnl"] == 1000

    trades = client.get(
        "/account/entrusts?start=2026-11-01&end=2026-11-05&instrument_code=510500"
    )
    assert trades.status_code == 200
    item = trades.json()["items"][0]
    assert item["side"] == "buy"
    assert item["fee_amount"] == 7
    assert item["display_time"] == "09:44:41.116"

    status = client.get("/account/sync/status")
    assert status.status_code == 200
    assert status.json()["latest"]["status"] == "success"


def test_complete_snapshot_excludes_disappeared_positions_and_records_empty():
    """同源日期第二次完整同步必须替换集合；合法空仓不沿用历史正持仓。"""

    def sync(rows):
        return sync_account(
            config=account_config(),
            fetch_holdings_fn=lambda _: rows,
            fetch_entrust_fn=lambda *_: [],
            today=date(2026, 11, 5),
        )

    sync([holding_row(), {**holding_row(), "STOCK_CODE": "159205"}])
    sync([{**holding_row(), "STOCK_CODE": "159205"}])
    holdings = client.get("/account/holdings").json()
    assert [r["instrument_code"] for r in holdings["items"]] == ["159205"]
    assert client.get("/research/universe").json()["held_codes"] == ["159205"]
    assert [
        r["instrument_code"]
        for r in client.get("/strategy-lab/catalog").json()["items"]
    ] == ["159205"]
    sync([])
    assert client.get("/account/holdings").json()["items"] == []
    assert client.get("/research/universe").json()["held_codes"] == []
    assert client.get("/strategy-lab/catalog").json()["items"] == []


def test_current_snapshot_is_consistent_during_same_day_sync():
    """在集合读取中间提交第二次同步，查询仍应返回一个完整版本。"""
    from sqlalchemy import event

    from app.account_state import latest_holdings
    from app.db import engine

    def sync(rows):
        return sync_account(
            config=account_config(),
            fetch_holdings_fn=lambda _: rows,
            fetch_entrust_fn=lambda *_: [],
            today=date(2026, 11, 5),
        )

    sync([holding_row(), {**holding_row(), "STOCK_CODE": "159205"}])
    fired = False

    def during_read(connection, cursor, statement, parameters, context, executemany):
        nonlocal fired
        if (
            not fired
            and statement.lstrip().startswith("SELECT")
            and "account_sync_runs" in statement
        ):
            fired = True
            sync([{**holding_row(), "STOCK_CODE": "159205"}])

    event.listen(engine, "after_cursor_execute", during_read)
    try:
        with Session() as db:
            _, rows = latest_holdings(db)
            assert {r.instrument_code for r in rows} in (
                {"159205", "510500"},
                {"159205"},
            )
        assert fired
    finally:
        event.remove(engine, "after_cursor_execute", during_read)
