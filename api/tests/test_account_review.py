"""真实复盘现金流、分红和完整性边界。"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.account_review import calculate_actual, coverage_gaps


def trade(day, side, qty, balance, clear):
    return {
        "curr_date": date.fromisoformat(day),
        "entrust_side": side,
        "business_amount": D(qty),
        "business_balance": D(balance),
        "clear_balance": D(clear),
        "entrust_no": day + side,
    }


def test_fees_once_and_nonzero_opening():
    trades = [
        trade("2026-01-05", "1", "1000", "10000", "10001"),
        trade("2026-01-06", "2", "400", "4800", "4799.52"),
    ]
    prices = [
        (date(2026, 1, 2), D(9)),
        (date(2026, 1, 5), D(10)),
        (date(2026, 1, 6), D(11)),
    ]
    result = calculate_actual(trades, prices, [], date(2026, 1, 5), date(2026, 1, 6))
    assert D(result["net_pnl"]) == D("1398.52")
    assert D(result["fees"]) == D("1.48")
    assert D(result["realized_pnl"]) == D("799.12")
    assert D(result["unrealized_pnl"]) == D("599.40")
    sub = calculate_actual(trades, prices, [], date(2026, 1, 6), date(2026, 1, 6))
    assert D(sub["initial_asset"]) == D(10000)
    assert D(sub["net_pnl"]) == D("1399.52")


def test_dividend_receivable_survives_sale_and_subperiod():
    trades = [
        trade("2026-01-05", "1", "100", "1000", "1000"),
        trade("2026-01-07", "2", "100", "990", "990"),
    ]
    prices = [
        (date(2026, 1, d), D("9.9" if d >= 6 else "10")) for d in (2, 5, 6, 7, 8, 9)
    ]
    events = [
        {
            "record_date": "2026-01-05",
            "ex_date": "2026-01-06",
            "pay_date": "2026-01-09",
            "cash_per_share": "0.1",
        }
    ]
    result = calculate_actual(
        trades, prices, events, date(2026, 1, 7), date(2026, 1, 8)
    )
    assert D(result["final_receivable"]) == 10
    assert D(result["net_pnl"]) == 0
    result = calculate_actual(
        trades, prices, events, date(2026, 1, 9), date(2026, 1, 9)
    )
    assert D(result["initial_asset"]) == 10
    assert D(result["dividends_paid"]) == 10
    assert D(result["net_pnl"]) == 0


def test_t_plus_one_and_negative_fee_rejected():
    prices = [(date(2026, 1, d), D(10)) for d in (2, 5)]
    trades = [
        trade("2026-01-05", "1", "100", "1000", "1000"),
        trade("2026-01-05", "2", "100", "1000", "1000"),
    ]
    with pytest.raises(ValueError, match="T\\+1"):
        calculate_actual(trades, prices, [], date(2026, 1, 5), date(2026, 1, 5))
    with pytest.raises(ValueError, match="费用"):
        calculate_actual(
            [trade("2026-01-05", "1", "100", "1000", "999")],
            prices,
            [],
            date(2026, 1, 5),
            date(2026, 1, 5),
        )


def test_successful_windows_must_cover_every_calendar_day():
    start, end = date(2026, 1, 1), date(2026, 1, 5)
    assert coverage_gaps(
        [(start, date(2026, 1, 2)), (date(2026, 1, 4), end)], start, end
    )
    assert not coverage_gaps(
        [(start, date(2026, 1, 3)), (date(2026, 1, 4), end)], start, end
    )


def test_same_day_opposite_sides_do_not_guess_average_cost_order():
    trades = [
        trade("2026-01-05", "1", "100", "1000", "1000"),
        trade("2026-01-06", "1", "100", "1200", "1200"),
        trade("2026-01-06", "2", "50", "550", "550"),
    ]
    prices = [(date(2026, 1, d), D(10)) for d in (2, 5, 6)]
    result = calculate_actual(trades, prices, [], date(2026, 1, 5), date(2026, 1, 6))
    assert D(result["net_pnl"]) == D(-150)
    assert result["realized_pnl"] is None
    assert result["unrealized_pnl"] is None


def test_nontrading_payment_keeps_natural_cashflow_date():
    trades = [trade("2026-01-05", "1", "100", "1000", "1000")]
    prices = [
        (date(2026, 1, d), D("9.9" if d >= 6 else "10")) for d in (2, 5, 6, 7, 8, 9, 12)
    ]
    events = [
        {
            "record_date": "2026-01-05",
            "ex_date": "2026-01-06",
            "pay_date": "2026-01-10",
            "cash_per_share": "0.1",
        }
    ]
    result = calculate_actual(
        trades, prices, events, date(2026, 1, 5), date(2026, 1, 12)
    )
    assert {"trade_date": "2026-01-10", "amount": "10.00"} in result["cashflows"]
    sub = calculate_actual(trades, prices, events, date(2026, 1, 12), date(2026, 1, 12))
    assert D(sub["initial_asset"]) == 990
    assert D(sub["dividends_paid"]) == 0
    assert D(sub["net_pnl"]) == 0
