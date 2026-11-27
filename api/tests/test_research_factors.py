from datetime import date, timedelta

import pytest

from app.research_factors import FACTORS, calculate_factor_events, factor_truth_rows


def rows_from_closes(closes, *, volumes=None, highs=None, lows=None):
    start = date(2025, 1, 1)
    volumes = volumes or [100.0] * len(closes)
    highs = highs or [value + 0.2 for value in closes]
    lows = lows or [value - 0.2 for value in closes]
    return [
        {
            "trade_date": str(start + timedelta(days=index)),
            "open": closes[index],
            "high": highs[index],
            "low": lows[index],
            "close": closes[index],
            "volume": volumes[index],
        }
        for index in range(len(closes))
    ]


def test_factor_directory_declares_observable_identity_and_output_type():
    assert set(FACTORS) == {
        "turning_bottom",
        "turning_top",
        "ma5_cross_ma20_up",
        "box_breakout_up",
        "volume_breakout_up",
        "atr_oversold",
        "wilder_rsi_oversold",
        "ma60_rising",
        "strong_close",
        "atr_box_breakout",
        "close_above_prior_high",
        "recovery_volume_band",
        "below_ma20",
        "close_position_positive",
        "lower_shadow_support",
        "atr_overbought",
        "wilder_rsi_overbought_turn_down",
        "close_cross_ma10_down",
        "ma5_cross_ma10_down",
        "ma5_cross_ma20_down",
        "high_volume_stall",
        "upper_shadow_rejection",
        "atr_volatility_high",
        "volatility_contracting",
        "volatility_expanding",
        "ma20_ma60_bullish",
        "trend_pullback_near_ma20",
        "valuation_low_percentile",
        "valuation_high_percentile",
        "sentiment_extreme_fear",
        "sentiment_fear_rebound",
        "sentiment_extreme_greed",
    }
    assert "oversold_recovery" not in FACTORS
    assert FACTORS["turning_bottom"]["output_type"] == "event"
    assert FACTORS["atr_oversold"]["output_type"] == "state"
    assert FACTORS["close_above_prior_high"]["output_type"] == "event"
    assert FACTORS["atr_overbought"]["output_type"] == "state"
    assert FACTORS["wilder_rsi_overbought_turn_down"]["output_type"] == "event"
    assert FACTORS["valuation_low_percentile"]["output_type"] == "state"
    assert all(item["name"] and item["category"] and item["meaning"] for item in FACTORS.values())


def test_reversal_atoms_do_not_require_the_old_composite_recovery_factor():
    closes = [10.0] * 20 + [9.3, 9.8]
    rows = rows_from_closes(
        closes,
        volumes=[100.0] * 21 + [120.0],
        highs=[10.1] * 20 + [9.5, 9.7],
        lows=[9.9] * 20 + [9.2, 8.8],
    )
    rows[-1].update(open=9.5, high=10.0, low=8.8)

    truth = factor_truth_rows(rows, {})

    assert truth[-1]["close_above_prior_high"] is True
    assert truth[-1]["recovery_volume_band"] is True
    assert truth[-1]["below_ma20"] is True
    assert truth[-1]["close_position_positive"] is True
    assert truth[-1]["lower_shadow_support"] is True


def test_profit_taking_and_regime_factors_have_distinct_truths():
    closes = [10 + index * 0.4 for index in range(70)]
    closes.extend([closes[-1] - 0.2, closes[-1] - 5.0])
    rows = rows_from_closes(closes, volumes=[100.0] * 71 + [260.0])
    rows[-1].update(open=33.0, high=42.0, low=closes[-1] - 0.2)

    truth = factor_truth_rows(rows, {})

    assert any(item["atr_overbought"] for item in truth)
    assert truth[-2]["wilder_rsi_overbought_turn_down"] is True
    assert truth[-1]["close_cross_ma10_down"] is True
    assert truth[-1]["high_volume_stall"] is True
    assert truth[-1]["upper_shadow_rejection"] is True
    assert any(item["ma20_ma60_bullish"] for item in truth)


def test_factor_events_are_causal_and_only_emit_breakout_on_crossing():
    closes = [10 + index * 0.01 for index in range(30)]
    closes.extend([10.8, 10.8, 10.8])
    rows = rows_from_closes(closes, highs=[value + 0.05 for value in closes])

    events = calculate_factor_events(rows, {})

    assert {event["factor_id"] for event in events if event["trade_date"] == rows[30]["trade_date"]} >= {
        "box_breakout_up",
    }
    assert not any(
        event["factor_id"] == "box_breakout_up" and event["trade_date"] == rows[31]["trade_date"]
        for event in events
    )


def test_factor_events_mark_wilder_oversold_atoms_and_turning_events():
    closes = [10.0] * 25 + [9.8, 9.5, 9.2, 9.0, 9.1, 9.3, 9.25]
    highs = [value + 0.1 for value in closes]
    highs[-1] = 9.4
    rows = rows_from_closes(
        closes,
        volumes=[100.0] * (len(closes) - 1) + [150.0],
        highs=highs,
        lows=[value - 0.15 for value in closes],
    )
    turning = {rows[-2]["trade_date"]: "bottom", rows[-1]["trade_date"]: "top"}

    events = calculate_factor_events(rows, turning)

    indexed = {(event["factor_id"], event["trade_date"]) for event in events}
    assert ("turning_bottom", rows[-2]["trade_date"]) in indexed
    assert ("turning_top", rows[-1]["trade_date"]) in indexed
    assert ("atr_oversold", rows[25]["trade_date"]) not in indexed
    assert ("atr_oversold", rows[26]["trade_date"]) in indexed
    assert ("close_above_prior_high", rows[-2]["trade_date"]) in indexed
    assert not any(event["factor_id"] == "oversold_recovery" for event in events)


def test_factor_events_need_history_for_wilder_indicators():
    events = calculate_factor_events(rows_from_closes([10.0, 10.1, 10.0]), {})

    assert events == []


def test_separates_wilder_oversold_from_atr_oversold_with_no_price_breakout():
    rows = rows_from_closes([10.0] * 14 + [9.99] * 9)
    events = calculate_factor_events(rows, {})
    indexed = {(item["factor_id"], item["trade_date"]) for item in events}
    assert ("wilder_rsi_oversold", rows[14]["trade_date"]) in indexed
    assert not any(item["factor_id"] == "atr_oversold" for item in events)
    assert not any(item["factor_id"] == "close_above_prior_high" for item in events)


def test_factor_truth_rows_keep_state_active_and_events_on_their_day_only():
    rows = rows_from_closes([10.0] * 14 + [9.99] * 9)
    turning = {rows[17]["trade_date"]: "bottom"}

    truth = factor_truth_rows(rows, turning)

    assert len(truth) == len(rows)
    assert truth[14]["trade_date"] == rows[14]["trade_date"]
    assert truth[14]["wilder_rsi_oversold"] is True
    assert truth[15]["wilder_rsi_oversold"] is True
    assert truth[17]["turning_bottom"] is True
    assert truth[18]["turning_bottom"] is False
    assert all(isinstance(item[factor_id], bool) for item in truth for factor_id in FACTORS)

    events = calculate_factor_events(rows, turning)
    rsi_days = [
        event["trade_date"]
        for event in events
        if event["factor_id"] == "wilder_rsi_oversold"
    ]
    assert rsi_days == [rows[14]["trade_date"]]


def test_unknown_turning_event_kind_is_rejected():
    rows = rows_from_closes([10.0, 10.1])
    with pytest.raises(ValueError, match="顶底事件类型无效"):
        calculate_factor_events(rows, {rows[-1]["trade_date"]: "sideways"})
