"""研究候选与风险统计的可手算验证。"""

from decimal import Decimal

import pytest
from test_backtest import bars, config

from app import strategies
from app.backtest import run_backtest


def test_confirmation_requires_positive_momentum_only_for_entry():
    rule = strategies.get_strategy("ma_momentum")
    rows = bars([10, 8, 9, 9.5, 10, 9.8, 9.7, 7])
    result = rule["prepare"](rows, [], {"window": 3, "momentum_window": 2})
    assert result[2]["decision"].target == 0
    assert result[3]["decision"].target == 1
    assert result[6]["decision"].target == 0
    changed = bars([10, 8, 9, 9.5, 10, 90, 90, 90])
    assert (
        result[:5]
        == rule["prepare"](changed, [], {"window": 3, "momentum_window": 2})[:5]
    )


def test_hold_rule_runs_in_same_engine():
    result = run_backtest(
        bars([10, 11, 12, 13, 12, 11]), [], config(strategy_key="hold", parameters={})
    )
    assert result["strategy"]["daily"] == result["benchmark"]["daily"]
    assert len(result["strategy"]["trades"]) == 1


def test_reserve_preserves_cash_and_reports_against_fifty_thousand():
    from app.strategy_research import with_reserve

    result = run_backtest(
        bars([10, 10, 10, 12, 11, 8]),
        [],
        config(initial_cash="25000", strategy_key="hold", parameters={}),
    )
    account = with_reserve(result["strategy"], Decimal(25000))
    assert Decimal(account["daily"][-1]["equity"]) == 45000
    assert account["metrics"]["total_return"] == pytest.approx(-0.1)
    assert account["metrics"]["max_drawdown"] == pytest.approx(45000 / 55000 - 1)
    assert account["daily"][0]["cash"] == "25000.00"
    assert account["daily"][0]["position_weight"] == 0.5


def test_complete_rounds_are_net_of_both_commissions():
    from app.strategy_research import diagnostics

    result = run_backtest(
        bars([10, 12, 11, 9, 11, 13], [10, 12, 12, 10, 11, 12]),
        [],
        config(commission_rate="0.0001"),
    )["strategy"]
    info = diagnostics(result, Decimal(10000))
    assert info["completed_rounds"] == 1
    assert info["open_rounds"] == 1
    assert info["rounds"][0]["pnl"] == "-1601.76"
    assert info["longest_underwater_days"] >= 1
