"""校验箱体研究的退出、训练边界与成交结果。"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.algorithm_templates import template_snapshot
from app.strategy_workbench import execute_candidate
from research_range_breakout import (
    BASELINE,
    atr_exit_policy,
    eligible,
    evaluate,
    prepare_market,
)


def market(prices):
    return {
        "rows": [
            {
                "trade_date": str(date(2025, 1, 1) + timedelta(days=i)),
                "open": str(price),
                "high": str(price * 1.01),
                "low": str(price * 0.99),
                "close": str(price),
                "volume": "100000" if i < 65 else "130000",
            }
            for i, price in enumerate(prices)
        ],
        "actions": {"dividends": [], "splits": []},
    }


def test_baseline_matches_application_on_actual_simulated_fills():
    item = market([1] * 65 + [1.02 + n * 0.004 for n in range(35)])
    data = prepare_market(item)
    start, end = item["rows"][64]["trade_date"], item["rows"][-1]["trade_date"]
    study = evaluate(data, BASELINE, start, end)
    snapshot = {"market": item, "external": {}, "settings": study["settings"]}
    candidate = {"template": template_snapshot("range_breakout", "1.0.0", "510500")}
    _, live, _ = execute_candidate(candidate, snapshot)
    assert len(live["trades"]) >= 2
    assert study["trades"] == live["trades"]
    assert study["metrics"] == live["metrics"]


def test_filter_features_are_causal_when_more_bars_are_loaded():
    item = market([1 + n * 0.003 for n in range(90)])
    prefix = {**item, "rows": item["rows"][:75]}
    assert prepare_market(item)["context"][:75] == prepare_market(prefix)["context"]


def test_atr_initial_stop_uses_previous_signal_and_trailing_does_not_widen():
    context = [
        {"raw_atr": 0.02},
        {"raw_atr": 0.03},
        {"raw_atr": 0.01},
        {"raw_atr": 0.06},
    ]
    factors = [
        {
            "top_age": 100,
            "bias": {10: 0, 20: 0},
            "momentum": {1: 0, 3: 0},
            "rsi": {14: 50},
        }
    ] * len(context)
    policy = atr_exit_policy(context, {"atr_stop": 2, "atr_trail": 2.5, "atr_days": 18})
    assert policy(1, 1, 1, -0.05, 0, factors[1]) == ["ATR初始止损"]
    assert policy(1, 1, 1, 0, 0, factors[1]) == []
    assert policy(2, 1, 1, 0.065, 0.065, factors[2]) == []
    assert policy(3, 1, 1, 0.035, 0.065, factors[3]) == ["ATR移动退出"]


def test_eligibility_counts_completed_trades_and_uses_exact_win_fraction():
    good = {
        "completed": 5,
        "wins": 4,
        "mean_pnl": 100,
        "metrics": {"total_return": 0.02},
    }
    assert eligible(good, 5)
    assert not eligible(good, 8)
    assert not eligible({**good, "completed": 6}, 5)
    assert not eligible({**good, "mean_pnl": -100}, 5)
