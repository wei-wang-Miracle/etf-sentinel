"""扩展技术指标的窗口、预热和因果边界。"""

import pytest

from app.indicators import (
    consecutive_down_count,
    drawdown_from_peak,
    excess_return,
    rolling_sma,
    wilder_adx14,
)


def _adx_series(highs, lows, closes):
    state = {}
    output = []
    for index, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True)):
        previous_high = highs[index - 1] if index else high
        previous_low = lows[index - 1] if index else low
        previous_close = closes[index - 1] if index else close
        plus_di, minus_di, adx, state = wilder_adx14(
            previous_high,
            previous_low,
            previous_close,
            high,
            low,
            close,
            index,
            state,
        )
        output.append((plus_di, minus_di, adx))
    return output


def test_rolling_indicators_require_only_declared_window_and_do_not_use_future_values():
    values = [10.0, 12.0, 11.0, 14.0, 13.0]
    benchmark = [100.0, 102.0, 101.0, 103.0, 104.0]

    assert rolling_sma(values, 1, 3) is None
    assert rolling_sma(values, 2, 3) == pytest.approx(11.0)
    assert drawdown_from_peak(values, 3, 3) == pytest.approx(0.0)
    assert drawdown_from_peak(values, 4, 3) == pytest.approx(-1 / 14)
    assert consecutive_down_count([10.0, 9.0, 8.0, 8.0], 2) == 2
    assert consecutive_down_count([10.0, 9.0, 8.0, 8.0], 3) == 0
    assert excess_return(values, benchmark, 1, 3) is None
    assert excess_return(values, benchmark, 3, 3) == pytest.approx(
        14 / 10 - 103 / 100
    )

    original = rolling_sma(values, 3, 3)
    values[-1] = 10_000.0
    assert rolling_sma(values, 3, 3) == original


def test_wilder_adx_waits_for_28_observations_and_is_causal():
    closes = [100.0 + index for index in range(31)]
    highs = [value + 1.0 for value in closes]
    lows = [value - 1.0 for value in closes]

    baseline = _adx_series(highs, lows, closes)

    assert all(item[2] is None for item in baseline[:27])
    plus_di, minus_di, adx = baseline[27]
    assert plus_di is not None and minus_di is not None and adx is not None
    assert plus_di > minus_di
    assert 0 <= adx <= 100
    assert baseline[28][2] is not None

    highs[-1], lows[-1], closes[-1] = 10_000.0, 1.0, 5_000.0
    assert _adx_series(highs, lows, closes)[:30] == baseline[:30]
