"""验证研究汇总信号的因果性、持仓状态与风险口径。"""

from copy import deepcopy
from datetime import date, timedelta

from app.multifactor_research import DEFAULT_RULE, build_factors, prepare_signals


def market(prices):
    """构造无权益事件的连续日序列，仅用于信号单元测试。"""
    return [
        {"trade_date": str(date(2025, 1, 1) + timedelta(days=i)),
         "open": str(p), "high": str(p * 1.01), "low": str(p * .99),
         "close": str(p), "volume": "100000", "adjusted_close": str(p)}
        for i, p in enumerate(prices)
    ]


def test_future_rows_cannot_change_past_signals():
    rows = market([10 + i * .01 for i in range(130)])
    short = prepare_signals(rows[:100], [], build_factors(rows[:100], [], {}), DEFAULT_RULE, 60)
    extended = prepare_signals(rows, [], build_factors(rows, [], {}), DEFAULT_RULE, 60)
    assert short == extended[:100]


def test_valuation_uses_previous_exact_date_and_missing_blocks_entry():
    rows = market([10 + i * .01 for i in range(80)])
    external = {"pe_percentile": {rows[60]["trade_date"]: {"value": "20"}}}
    factors = build_factors(rows, [], {}, external)
    assert factors[60]["pe_percentile"] is None
    assert factors[61]["pe_percentile"] == 20
    assert factors[62]["pe_percentile"] is None
    rule = {**DEFAULT_RULE, "family": "breakout", "value_metric": "pe_percentile", "value_max": 50}
    missing = prepare_signals(rows, [], build_factors(rows, [], {}), rule, 60)
    assert all(s["decision"].target == 0 for s in missing)


def test_single_bottom_factor_does_not_directly_create_buy():
    rows = market([10 - i * .01 for i in range(80)])
    factors = build_factors(rows, [], {rows[65]["trade_date"]: "bottom"})
    rule = {**DEFAULT_RULE, "family": "bottom", "buy_votes": 4, "volume_min": 2}
    signals = prepare_signals(rows, [], factors, rule, 60)
    assert signals[65]["indicators"]["buy"]["structure"] is True
    assert signals[65]["decision"].target == 0


def test_risk_exit_works_with_missing_valuation_and_next_open_fill():
    rows = market([10 + i * .01 for i in range(80)])
    rows[62].update(open="15", high="15.1", low="10", close="10.62")
    factors = build_factors(rows, [], {})
    # 人工冻结当日因子，以隔离风险状态与估值缺失行为。
    for f in factors:
        f["pe_percentile"] = None
    factors[61]["pe_percentile"] = 10
    rule = {**DEFAULT_RULE, "family": "breakout", "value_metric": "pe_percentile",
            "value_max": 50, "stop_loss": .05}
    signals = prepare_signals(rows, [], factors, rule, 60)
    assert signals[61]["decision"].target == 1
    assert signals[62]["decision"].target == 0
    assert "止损" in signals[62]["decision"].reason
    assert signals[62]["indicators"]["entry_price"] == "15.008"
    costly = prepare_signals(rows, [], factors, rule, 60, slippage_bps=10)
    assert costly[62]["indicators"]["entry_price"] == "15.015"


def test_max_holding_exit_and_sell_priority():
    rows = market([10 + i * .01 for i in range(100)])
    rule = {**DEFAULT_RULE, "family": "breakout", "max_holding": 5,
            "take_profit": .2, "sell_votes": 3}
    signals = prepare_signals(rows, [], build_factors(rows, [], {}), rule, 60)
    assert signals[60]["decision"].target == 1
    assert signals[65]["decision"].target == 0
    assert "持有期限" in signals[65]["decision"].reason
    assert signals[65]["indicators"]["buy_score"] >= rule["buy_votes"]


def test_dividend_drop_does_not_trigger_false_price_stop():
    rows = market([10] * 61 + [10.2] * 2 + [9.2] * 10)
    dividends = [{"record_date": rows[62]["trade_date"], "ex_date": rows[63]["trade_date"],
                  "pay_date": rows[65]["trade_date"], "cash_per_share": "1"}]
    factors = build_factors(rows, dividends, {})
    for f in factors:
        f["top_age"] = 10000
    rule = {**DEFAULT_RULE, "family": "breakout", "stop_loss": .05,
            "sell_votes": 3, "max_holding": 60}
    signals = prepare_signals(rows, dividends, factors, rule, 60)
    assert signals[61]["decision"].target == 1
    assert "止损" not in signals[63]["decision"].reason
    assert signals[63]["indicators"]["holding_return"] > -.01
    changed = deepcopy(rows)
    changed[-1]["close"] = "1"
    assert signals[:-1] == prepare_signals(changed, dividends, build_factors(changed, dividends, {}), rule, 60)[:-1]


def test_research_exit_policy_does_not_override_existing_entries():
    rows = market([10 + i * .01 for i in range(80)])
    rule = {**DEFAULT_RULE, "family": "breakout", "max_holding": 30}
    factors = build_factors(rows, [], {})
    base = prepare_signals(rows, [], factors, rule, 60)

    def exit_policy(i, entry_index, entry_price, holding_return, peak, factor):
        return ["研究时间止损"] if i == entry_index + 1 else []

    trial = prepare_signals(rows, [], factors, rule, 60, exit_policy=exit_policy)
    assert trial[:61] == base[:61]
    assert trial[61]["decision"].target == 1
    assert trial[62]["decision"].target == 0
    assert trial[62]["decision"].reason == "汇总卖出：研究时间止损"
    assert base[62]["decision"].target == 1
