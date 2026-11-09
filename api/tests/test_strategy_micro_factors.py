"""验证日K微观因子的预热、事件边界与因果性。"""

from copy import deepcopy
from decimal import Decimal

import pytest
from test_backtest import bars
from test_strategy_conditions import condition, rule

from app.strategy_conditions import prepare_conditions, validate_rule, warmup_days


def checks(prices, item, volumes=None, dividends=None):
    """提取买入条件证据，隔离持仓状态对因子断言的影响。"""
    rows = bars(prices)
    if volumes:
        for row, volume in zip(rows, volumes, strict=True):
            row["volume"] = volume
    return [
        p["indicators"]["buy"][0]
        for p in prepare_conditions(rows, dividends or [], {"rule": rule([item])})
    ]


def test_double_average_and_slope_use_complete_windows():
    spread = condition("ma_spread", window=2, long_window=3)
    result = checks([10, 10, 10, 13], spread)
    assert result[1]["value"] is None
    assert float(result[3]["value"]) == pytest.approx((11.5 / 11 - 1) * 100)
    slope = condition("ma_slope", window=2, lag=2)
    result = checks([10, 10, 12, 14], slope)
    assert result[2]["value"] is None
    assert Decimal(result[3]["value"]) == 30
    assert warmup_days(rule([spread, slope])) == 4


@pytest.mark.parametrize(
    "indicator,extra", [("price_cross", {}), ("ma_cross", {"long_window": 3})]
)
def test_cross_only_occurs_on_crossing_day_after_equality(indicator, extra):
    item = condition(indicator, "cross_up", window=2, **extra)
    result = checks([10, 10, 10, 12, 13], item)
    assert result[1]["satisfied"] is None
    assert result[2]["satisfied"] is (False if indicator == "price_cross" else None)
    assert result[3]["satisfied"] is True
    assert result[4]["satisfied"] is False


def test_volume_ratios_exclude_today_only_for_previous_average():
    item = condition("volume_ratio", "gt", "2", 2)
    result = checks([10] * 4, item, ["10", "20", "60", "0"])
    assert result[1]["value"] is None
    assert Decimal(result[2]["value"]) == 4
    assert result[2]["satisfied"] is True
    assert Decimal(result[3]["value"]) == 0
    result = checks(
        [10] * 3,
        condition("volume_ma_ratio", window=2, long_window=3),
        ["10", "20", "60"],
    )
    assert Decimal(result[2]["value"]) == Decimal(4) / 3
    assert checks([10] * 3, item, ["0", "0", "10"])[2]["value"] is None
    assert checks([10] * 3, item, ["10", None, "10"])[2]["value"] is None


def test_breakout_uses_previous_closes_and_strict_boundary():
    item = condition("breakout", "cross_up", window=2)
    result = checks([10, 11, 11, 12], item)
    assert result[1]["satisfied"] is None
    assert result[2]["satisfied"] is False
    assert result[3]["satisfied"] is True
    down = checks([10, 9, 9, 8], {**item, "operator": "cross_down"})
    assert down[2]["satisfied"] is False
    assert down[3]["satisfied"] is True


@pytest.mark.parametrize(
    "indicator,extra",
    [
        ("ma_spread", {"long_window": 3}),
        ("ma_slope", {"lag": 2}),
        ("price_cross", {"operator": "cross_up"}),
        ("ma_cross", {"operator": "cross_down", "long_window": 3}),
        ("volume_ratio", {}),
        ("volume_ma_ratio", {"long_window": 3}),
        ("breakout", {"operator": "cross_up"}),
    ],
)
def test_new_factors_never_read_future(indicator, extra):
    item = {**condition(indicator), **extra}
    rows = bars([10, 12, 11, 13, 12, 15])
    changed = deepcopy(rows)
    changed[-1].update(close="200", volume="9000000")
    spec = {"rule": rule([item])}
    assert (
        prepare_conditions(rows, [], spec)[:-1]
        == prepare_conditions(changed, [], spec)[:-1]
    )


@pytest.mark.parametrize(
    "item",
    [
        condition("ma_spread", long_window=2),
        condition("ma_cross", "cross_up", long_window=True),
        condition("ma_slope", lag=0),
        condition("ma_slope", lag=True),
        condition("price_cross"),
        condition("breakout", "gte"),
        condition("trend", "cross_up"),
    ],
)
def test_invalid_micro_parameters_are_rejected(item):
    with pytest.raises(ValueError):
        validate_rule(rule([item]))


def test_dividend_does_not_create_spurious_down_cross():
    item = condition("price_cross", "cross_down", window=2)
    result = checks(
        [10, 10, 9, 9],
        item,
        dividends=[
            {
                "ex_date": "2026-01-03",
                "cash_per_share": "1",
            }
        ],
    )
    assert result[2]["satisfied"] is False


def test_diagnostics_count_decision_days_separately_from_trades_and_warmup():
    from app.strategy_conditions import condition_diagnostics

    rows = bars([10, 10, 12, 13, 8])
    spec = rule([condition(window=2)])
    signals = prepare_conditions(rows, [], {"rule": spec})
    account = {
        "daily": [{"trade_date": r["trade_date"]} for r in rows[2:]],
        "trades": [{"side": "buy"}],
    }
    stats = condition_diagnostics(spec, rows, signals, account)
    assert stats["days"] == 3
    assert stats["decision_start"] == "2026-01-02"
    assert stats["decision_end"] == "2026-01-04"
    assert stats["buy"]["matched_days"] == 2
    assert stats["sell"]["matched_days"] == 1
    assert stats["buy_trades"] == 1 and stats["sell_trades"] == 0
    assert stats["buy"]["conditions"][0]["valid_days"] == 3
