"""以可手算账本验证统一回测的因果边界与真实现金核算。"""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from app.backtest import run_backtest


def bars(prices, opens=None):
    """生成连续测试日行情；交易日完整性由服务层另行校验。"""
    return [
        {
            "trade_date": str(date(2026, 1, 1) + timedelta(days=i)),
            "open": str((opens or prices)[i]),
            "high": str(max(p, (opens or prices)[i]) + 1),
            "low": str(min(p, (opens or prices)[i]) - 1),
            "close": str(p),
            "volume": "1000000",
            "adjusted_close": str(p),
        }
        for i, p in enumerate(prices)
    ]


def config(**changes):
    """免成本测试默认值便于独立手算。"""
    return {
        "strategy_key": "ma_trend",
        "parameters": {"window": 2},
        "initial_cash": "10000",
        "commission_rate": "0",
        "minimum_commission": "0",
        "slippage_bps": "0",
        "start_date": "2026-01-03",
        "end_date": "2026-01-06",
        **changes,
    }


def test_close_signal_executes_next_open_and_never_spends_negative_cash():
    result = run_backtest(
        bars([10, 12, 11, 9, 11, 13], [10, 12, 12, 10, 11, 12]), [], config()
    )
    trades = result["strategy"]["trades"]
    assert [(t["trade_date"], t["side"], t["quantity"]) for t in trades] == [
        ("2026-01-03", "buy", 800),
        ("2026-01-04", "sell", 800),
        ("2026-01-06", "buy", 700),
    ]
    assert trades[0]["signal_date"] == "2026-01-02"
    assert D(result["strategy"]["daily"][-1]["equity"]) == D(9100)
    assert all(D(r["cash"]) >= 0 for r in result["strategy"]["daily"])


def test_future_price_changes_do_not_change_prior_decisions():
    original = bars([10, 12, 11, 9, 11, 13])
    changed = bars([10, 12, 11, 9, 50, 60])
    a = run_backtest(original, [], config())["strategy"]["daily"]
    b = run_backtest(changed, [], config())["strategy"]["daily"]
    assert a[:2] == b[:2]


def test_commission_minimum_slippage_tick_and_whole_lots():
    result = run_backtest(
        bars([10, 11, 10]),
        [],
        config(
            end_date="2026-01-03",
            slippage_bps="5",
            commission_rate="0.0001",
            minimum_commission="5",
        ),
    )
    trade = result["strategy"]["trades"][0]
    assert D(trade["price"]) == D("10.005")
    assert trade["quantity"] == 900
    assert D(trade["commission"]) == D(5)
    assert D(result["strategy"]["daily"][0]["cash"]) == D("990.50")


def test_dividend_right_survives_sale_and_cash_only_arrives_on_payment_day():
    source = bars([10, 11, 12, 10, 9, 9], [10, 11, 10, 10, 9, 9])
    events = [
        {
            "record_date": "2026-01-03",
            "ex_date": "2026-01-05",
            "pay_date": "2026-01-06",
            "cash_per_share": "1",
        }
    ]
    result = run_backtest(source, events, config())["strategy"]
    assert result["trades"][1]["trade_date"] == "2026-01-05"
    daily = result["daily"]
    assert D(daily[2]["dividend_receivable"]) == D(1000)
    assert D(daily[2]["cash"]) == D(9000)
    assert D(daily[3]["dividend_receivable"]) == 0
    assert D(daily[3]["cash"]) == D(10000)
    assert D(daily[3]["equity"]) == D(10000)


def test_ex_date_buy_does_not_receive_dividend_and_benchmark_uses_same_costs():
    events = [
        {
            "record_date": "2026-01-02",
            "ex_date": "2026-01-03",
            "pay_date": "2026-01-04",
            "cash_per_share": "1",
        }
    ]
    result = run_backtest(bars([9, 10, 10, 10]), events, config(end_date="2026-01-04"))
    assert all(D(r["dividend_receivable"]) == 0 for r in result["benchmark"]["daily"])
    assert (
        result["benchmark"]["trades"][0]["price"]
        == result["strategy"]["trades"][0]["price"]
    )


def test_insufficient_warmup_rejected_and_last_day_no_forced_liquidation():
    with pytest.raises(ValueError, match="预热"):
        run_backtest(bars([10, 11, 12]), [], config(parameters={"window": 3}))
    result = run_backtest(bars([10, 11, 12]), [], config(end_date="2026-01-03"))
    assert len(result["strategy"]["trades"]) == 1
    assert result["strategy"]["daily"][-1]["quantity"] > 0


def test_open_fill_does_not_read_intraday_high_low_or_volume():
    """前日信号与开盘相同时，未知盘中走势不能影响开盘成交。"""
    a = bars([10, 11, 10])
    b = bars([10, 11, 10])
    b[2].update(high="10", low="10", volume="0")
    settings = config(end_date="2026-01-03", slippage_bps="5")
    assert (
        run_backtest(a, [], settings)["strategy"]["trades"]
        == run_backtest(b, [], settings)["strategy"]["trades"]
    )


def test_registered_rule_reuses_account_engine_without_mean_average(monkeypatch):
    """注册一个测试规则即可复用成交与账户，不要求均线字段。"""
    from app.strategies import REGISTRY, Decision

    monkeypatch.setitem(
        REGISTRY,
        "test_rule",
        {
            "metadata": {"key": "test_rule", "version": "test", "parameters": []},
            "prepare": lambda rows, dividends, params: [
                {"decision": Decision(1, "测试持有"), "indicators": {"test": "1"}}
                for _ in rows
            ],
        },
    )
    settings = {**config(), "strategy_key": "test_rule", "parameters": {}}
    settings.pop("window", None)
    result = run_backtest(bars([10, 11, 12]), [], settings)["strategy"]
    assert result["trades"][0]["reason"] == "测试持有"
    assert result["daily"][0]["indicators"] == {"test": "1"}


def test_flat_price_equal_to_average_does_not_generate_rounding_signal():
    """除法残差不能使横盘价格被误判为高于均线。"""
    from app.strategies import decide, features

    values = features(bars([3, 5, 7, 11, 11, 11, 11]), [], 2)
    assert all(decide("ma_trend", *pair).target == 0 for pair in values[4:])


def test_payment_date_cash_is_not_spent_before_known_receipt_time(monkeypatch):
    """源只有发放日期，保守按收盘入现金，不能用于该日开盘买入。"""
    from app.strategies import REGISTRY, Decision

    monkeypatch.setitem(
        REGISTRY,
        "payment_test",
        {
            "metadata": {"key": "payment_test", "parameters": []},
            "prepare": lambda rows, dividends, params: [
                {"decision": Decision(target, "测试"), "indicators": {}}
                for target in (1, 1, 0, 0, 1, 1)
            ],
        },
    )
    events = [
        {
            "record_date": "2026-01-03",
            "ex_date": "2026-01-05",
            "pay_date": "2026-01-06",
            "cash_per_share": "1",
        }
    ]
    account = run_backtest(
        bars([9, 10, 10, 9, 10, 10]),
        events,
        config(strategy_key="payment_test", parameters={}),
    )["strategy"]
    assert account["trades"][-1]["quantity"] == 900
    assert D(account["daily"][-1]["cash"]) == 1000
