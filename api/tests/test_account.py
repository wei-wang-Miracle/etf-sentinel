"""账户同步纯逻辑：窗口拆分、过滤、费用推导和增量起点。"""

import itertools
from datetime import date
from decimal import Decimal

import pytest

from app.account import (
    derive_fee,
    fetch_entrust_window,
    format_source_time,
    merge_entrust_rows,
    normalize_entrust,
    normalize_holding,
    split_windows,
    sync_start,
)


def test_split_windows_covers_range_without_overlap():
    windows = split_windows(date(2025, 1, 20), date(2025, 3, 5), days=30)
    assert windows[0][0] == date(2025, 1, 20)
    assert windows[-1][1] == date(2025, 3, 5)
    for left, right in itertools.pairwise(windows):
        assert left[1] < right[0]
        assert (right[0] - left[1]).days == 1
    assert sum((end - start).days + 1 for start, end in windows) == (
        date(2025, 3, 5) - date(2025, 1, 20)
    ).days + 1


def test_split_windows_empty_when_start_after_end():
    assert split_windows(date(2025, 2, 1), date(2025, 1, 1)) == []


def test_derive_fee_buy_and_sell():
    assert derive_fee("1", Decimal(5188), Decimal("5188.72")) == Decimal("0.72")
    assert derive_fee("2", Decimal(4806), Decimal("4805.32")) == Decimal("0.68")
    assert derive_fee("1", Decimal(100), Decimal(99)) == Decimal(0)
    assert derive_fee("9", Decimal(100), Decimal(101)) == Decimal(0)


def test_format_source_time():
    assert format_source_time(94441116) == "09:44:41.116"
    assert format_source_time("134827894") == "13:48:27.894"
    assert format_source_time(0) == "00:00:00.000"
    assert format_source_time(None) is None
    assert format_source_time("abc") is None


def test_normalize_holding_filters_and_whitelists():
    row = {
        "STOCK_CODE": "510500",
        "DATA_DATE": "20261105",
        "CURRENT_AMOUNT": 1000,
        "ENABLE_AMOUNT": 900,
        "FROZEN_AMOUNT": 100,
        "UNCOME_BUY_AMOUNT": 0,
        "UNCOME_SELL_AMOUNT": 0,
        "COST_PRICE": 7.215,
        "SUM_BUY_AMOUNT": 4600,
        "SUM_BUY_BALANCE": 33192.01,
        "SUM_SELL_AMOUNT": 3600,
        "SUM_SELL_BALANCE": 23783.72,
        "ETL_TIME": "2026-11-05 22:58:48",
        "FUND_ACCOUNT": "11240687",
        "POSITION_STR": "secret",
    }
    result = normalize_holding(row, {"510500"})
    assert result is not None
    assert result["instrument_code"] == "510500"
    assert result["data_date"] == date(2026, 11, 5)
    assert result["current_amount"] == Decimal(1000)
    assert result["cost_price"] == Decimal("7.215")
    assert "FUND_ACCOUNT" not in result and "POSITION_STR" not in result
    assert normalize_holding(row, {"512100"}) is None


def test_normalize_entrust_filters_and_derives_fee():
    row = {
        "CURR_DATE": "20260601",
        "INIT_DATE": "20260601",
        "CURR_TIME": 94441116,
        "ENTRUST_NO": 2992000000000001,
        "ORDER_ID": 2992000000000001,
        "STOCK_CODE": "560780",
        "ENTRUST_BS": "1",
        "ENTRUST_AMOUNT": 2000,
        "ENTRUST_PRICE": 2.598,
        "ENTRUST_TYPE": "0",
        "BUSINESS_AMOUNT": 2000,
        "BUSINESS_PRICE": 2.594,
        "BUSINESS_BALANCE": 5188,
        "CLEAR_BALANCE": 5188.72,
        "WITHDRAW_AMOUNT": 0,
        "ENTRUST_STATUS": "8",
        "FARE_KIND": 1001,
        "DATA_DATE": "20260601",
        "ETL_TIME": "2026-06-01 21:54:32",
        "OP_STATION": "device-secret",
        "CLIENT_NAME": "王*",
    }
    result = normalize_entrust(row, {"560780"})
    assert result is not None
    assert result["instrument_code"] == "560780"
    assert result["curr_date"] == date(2026, 6, 1)
    assert result["fee_amount"] == Decimal("0.72")
    assert "OP_STATION" not in result and "CLIENT_NAME" not in result
    assert normalize_entrust(row, {"510500"}) is None


def test_normalize_entrust_configured_invalid_raises():
    with pytest.raises(ValueError):
        normalize_entrust({"STOCK_CODE": "510500"}, {"510500"})


def test_merge_entrust_rows_keeps_latest():
    rows = [
        {"CURR_DATE": "20260601", "ENTRUST_NO": "1", "value": "old"},
        {"CURR_DATE": "20260601", "ENTRUST_NO": "2", "value": "two"},
        {"CURR_DATE": "20260601", "ENTRUST_NO": "1", "value": "new"},
    ]
    merged = merge_entrust_rows(rows)
    assert len(merged) == 2
    assert [r["value"] for r in merged if r["ENTRUST_NO"] == "1"] == ["new"]


def test_fetch_entrust_window_splits_at_cap():
    calls = []

    def fetch(start, end):
        calls.append((start, end))
        if (end - start).days > 10:
            return [
                {"CURR_DATE": start.strftime("%Y%m%d"), "ENTRUST_NO": str(i)}
                for i in range(1000)
            ]
        return [{"CURR_DATE": start.strftime("%Y%m%d"), "ENTRUST_NO": "x"}]

    rows = fetch_entrust_window(
        fetch, date(2025, 1, 1), date(2025, 1, 31), max_rows=1000
    )
    assert len(calls) > 1
    assert len(rows) >= 2
    assert all(date(2025, 1, 1) <= start <= end <= date(2025, 1, 31) for start, end in calls)


def test_fetch_entrust_window_single_day_cap_raises():
    def fetch(start, end):
        return [{"CURR_DATE": "20260601", "ENTRUST_NO": str(i)} for i in range(1000)]

    with pytest.raises(ValueError):
        fetch_entrust_window(
            fetch, date(2026, 6, 1), date(2026, 6, 1), max_rows=1000
        )


def test_sync_start_uses_default_or_overlap():
    default = date(2025, 1, 20)
    assert sync_start(None, date(2026, 11, 5), default) == default
    assert sync_start(date(2026, 6, 1), date(2026, 11, 5), default) == date(2026, 5, 25)
    assert sync_start(date(2025, 1, 22), date(2026, 11, 5), default) == default
    assert sync_start(date(2027, 1, 1), date(2026, 11, 5), default) == date(2026, 10, 29)
