"""验证共享研究策略的信号边界、风险状态和旧因子兼容。"""

from datetime import date, timedelta

import pytest

from app.algorithm_templates import turning_events
from app.shared_etf_research import RULES, prepare_market, prepare_shared


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


def test_breakout_needs_quality_and_volume_and_waits_for_prewarm():
    closes = [10 + i * 0.015 for i in range(64)] + [11.2, 11.1]
    rule = RULES["range_breakout"]
    rows = market(closes)
    blocked = prepare_shared(rows, [], prepare_market(rows, [], {}), rule, 0)
    assert blocked[63]["decision"] is None
    assert blocked[64]["indicators"]["trigger"]
    assert not blocked[64]["indicators"]["confirmations"]["volume"]
    assert blocked[64]["decision"].target == 0
    rows[64]["volume"] = "1500"
    ready = prepare_shared(rows, [], prepare_market(rows, [], {}), rule, 0)
    assert ready[64]["decision"].target == 1
    assert ready[65]["indicators"]["entry_price"] == pytest.approx(11.106)


def test_reversal_enters_below_ma20_without_turning_event_and_exits_at_ma20():
    rows = market([10] * 58 + [9.8, 9.6, 9.4, 9.2, 9, 9.02, 9.2, 9.24, 10.1])
    bars = prepare_market(rows, [], {})
    result = prepare_shared(rows, [], bars, RULES["bottom_reversal"], 0)
    assert bars[64]["value"] < bars[64]["ma20"]
    assert result[64]["decision"].target == 1
    assert result[65]["indicators"]["protection"] < 9.24
    assert result[66]["decision"].target == 0
    assert "回归MA20" in result[66]["decision"].reason


def test_protection_does_not_drop_on_atr_shock_or_future_append():
    closes = [10 + i * 0.015 for i in range(64)] + [11.2, 11.2, 12.2, 12.8, 11.95]
    rows = market(closes)
    rows[64]["volume"] = "1500"
    rows[-1].update(high="14", low="7")
    rule = RULES["range_breakout"]
    data = prepare_market(rows, [], {})
    result = prepare_shared(rows, [], data, rule, 0)
    prefix = prepare_shared(rows[:-1], [], prepare_market(rows[:-1], [], {}), rule, 0)
    assert result[:-1] == prefix
    assert data[-1]["atr"] > data[-2]["atr"]
    assert (
        result[-1]["indicators"]["protection"] == result[-2]["indicators"]["protection"]
    )
    assert result[-1]["decision"].target == 0


def test_wilder_seed_flat_and_old_turning_shape():
    rows = market([10] * 15 + [11, 10] + [10] * 70)
    data = prepare_market(rows, [], {})
    assert data[13]["rsi"] is None
    assert data[14]["rsi"] == 50
    assert data[15]["rsi"] == 100
    assert data[-1]["rsi"] == pytest.approx(100 * 13 / 27)
    assert set(turning_events(rows, [])) <= {row["trade_date"] for row in rows}


def test_two_of_three_only_relaxes_confirmation():
    rows = market([10 + i * 0.015 for i in range(64)] + [11.2, 11.1])
    bars = prepare_market(rows, [], {})
    rule = {**RULES["range_breakout"], "confirmations_required": 2}
    assert prepare_shared(rows, [], bars, rule, 0)[64]["decision"].target == 1
    bars[64]["margin"] = 0
    assert prepare_shared(rows, [], bars, rule, 0)[64]["decision"].target == 0


def test_reversal_without_breaking_previous_high_does_not_enter():
    rows = market([10] * 58 + [9.8, 9.6, 9.4, 9.2, 9, 9.02, 9.08])
    bars = prepare_market(rows, [], {})
    point = prepare_shared(rows, [], bars, RULES["bottom_reversal"], 0)[64]
    assert not point["indicators"]["trigger"]
    assert point["decision"].target == 0
