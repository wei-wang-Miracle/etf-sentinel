"""验证固定先验共享研究规则，不影响滚动寻优 v2.1。"""

from datetime import date, timedelta

import pytest


def market(closes, volumes=None):
    return [
        {
            "trade_date": str(date(2025, 1, 1) + timedelta(days=i)),
            "open": str(close),
            "high": str(close + 0.1),
            "low": str(close - 0.2),
            "close": str(close),
            "volume": str(volumes[i] if volumes else 1000),
        }
        for i, close in enumerate(closes)
    ]


def test_fixed_breakout_requires_registered_volume_ceiling():
    from app.shared_etf_research import (
        FIXED_PRIOR_RULES,
        prepare_fixed_prior,
        prepare_market,
    )

    rows = market([10 + i * 0.015 for i in range(64)] + [11.2, 11.1])
    rows[64]["volume"] = "2300"
    result = prepare_fixed_prior(
        rows, [], prepare_market(rows, [], {}), FIXED_PRIOR_RULES["range_breakout"], 0
    )
    assert result[64]["indicators"]["confirmations"]["volume"] is False
    assert result[64]["decision"].target == 0

    rows[64]["volume"] = "2200"
    result = prepare_fixed_prior(
        rows, [], prepare_market(rows, [], {}), FIXED_PRIOR_RULES["range_breakout"], 0
    )
    assert result[64]["decision"].target == 1


def test_fixed_left_reversal_filters_weak_close_and_caps_initial_loss():
    from app.shared_etf_research import (
        FIXED_PRIOR_RULES,
        prepare_fixed_prior,
        prepare_market,
    )

    rows = market([10] * 58 + [9.8, 9.6, 9.4, 9.2, 9, 9.02, 9.2, 9.24, 10.1])
    rows[62]["low"] = "1"
    rule = FIXED_PRIOR_RULES["left_reversal"]
    ready = prepare_fixed_prior(rows, [], prepare_market(rows, [], {}), rule, 0)
    assert ready[64]["decision"].target == 1
    entry = ready[65]["indicators"]
    assert entry["protection"] == pytest.approx(entry["entry_price"] * 0.95)

    rows[64]["high"] = "10.5"
    blocked = prepare_fixed_prior(rows, [], prepare_market(rows, [], {}), rule, 0)
    assert blocked[64]["indicators"]["confirmations"]["bar_quality"] is False
    assert blocked[64]["decision"].target == 0


def test_fixed_left_reversal_tightens_after_ma20_without_forcing_small_profit_exit():
    from app.shared_etf_research import (
        FIXED_PRIOR_RULES,
        prepare_fixed_prior,
        prepare_market,
    )

    rows = market([10] * 58 + [9.8, 9.6, 9.4, 9.2, 9, 9.02, 9.2, 9.24, 9.48, 9.7])
    result = prepare_fixed_prior(
        rows,
        [],
        prepare_market(rows, [], {}),
        FIXED_PRIOR_RULES["left_reversal"],
        0,
    )
    # 站上 MA20 但未达到 1.5 ATR 目标时，只抬高保护线而不立即发出卖出目标。
    point = result[67]
    assert point["indicators"]["ma20_tightened"] is True
    assert point["indicators"]["protection"] >= point["indicators"]["entry_price"]
    assert point["decision"].target == 1
