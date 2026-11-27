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
        "oversold_recovery",
        "wilder_rsi_oversold",
        "ma60_rising",
        "strong_close",
        "atr_box_breakout",
    }
    assert FACTORS["turning_bottom"]["output_type"] == "event"
    assert FACTORS["atr_oversold"]["output_type"] == "state"
    assert all(item["name"] and item["category"] and item["meaning"] for item in FACTORS.values())


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


def test_factor_events_mark_wilder_oversold_recovery_and_turning_events():
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
    assert ("oversold_recovery", rows[-2]["trade_date"]) in indexed


def test_factor_events_need_history_for_wilder_indicators():
    events = calculate_factor_events(rows_from_closes([10.0, 10.1, 10.0]), {})

    assert events == []


def test_separates_wilder_oversold_from_atr_oversold_with_no_price_breakout():
    rows = rows_from_closes([10.0] * 14 + [9.99] * 9)
    events = calculate_factor_events(rows, {})
    assert {item["factor_id"] for item in events} == {"wilder_rsi_oversold"}
    assert events[0]["trade_date"] == rows[14]["trade_date"]


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
