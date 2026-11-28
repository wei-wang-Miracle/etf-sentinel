"""供因子和离线研究复用的纯指标公式，不包含交易条件。"""

from statistics import fmean


def prior_close_margin(values, index, window):
    return (
        values[index] - max(values[index - window : index]) if index >= window else None
    )


def volume_ratio(volumes, index, window=20):
    if index < window:
        return None
    baseline = fmean(volumes[index - window : index])
    return volumes[index] / baseline if baseline > 0 else None


def wilder14(previous_close, close, high, low, index, atr, gain, loss):
    """递推 ATR14 和 RSI14 的平滑量；读取方负责首窗有效性。"""
    true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
    atr = atr + true_range / 14 if index < 14 else (13 * atr + true_range) / 14
    if index:
        delta = close - previous_close
        up, down = max(delta, 0), max(-delta, 0)
        if index <= 14:
            gain, loss = gain + up / 14, loss + down / 14
        else:
            gain, loss = (13 * gain + up) / 14, (13 * loss + down) / 14
    return atr, gain, loss


def rolling_sma(values, index, window):
    """返回截至当日的简单均线；预热不足时不推断数值。"""
    if window <= 0:
        raise ValueError("均线窗口必须为正数")
    if index < 0 or index >= len(values) or index + 1 < window:
        return None
    return fmean(values[index - window + 1 : index + 1])


def drawdown_from_peak(values, index, window):
    """返回当前值相对窗口内历史峰值的回撤，不读取当日之后的数据。"""
    if window <= 0:
        raise ValueError("回撤窗口必须为正数")
    if index < 0 or index >= len(values):
        return None
    peak = max(values[max(0, index - window + 1) : index + 1])
    return values[index] / peak - 1 if peak > 0 else None


def consecutive_down_count(values, index):
    """计算截至当日连续收跌交易日数，平盘会终止连续计数。"""
    if index <= 0 or index >= len(values):
        return 0
    count = 0
    for current in range(index, 0, -1):
        if values[current] >= values[current - 1]:
            break
        count += 1
    return count


def excess_return(values, benchmark_values, index, window):
    """返回相同观察窗口内 ETF 相对基准的收益差。"""
    if window <= 0:
        raise ValueError("相对强弱窗口必须为正数")
    if (
        index < window
        or index >= len(values)
        or index >= len(benchmark_values)
        or values[index - window] == 0
        or benchmark_values[index - window] == 0
    ):
        return None
    return (
        values[index] / values[index - window]
        - benchmark_values[index] / benchmark_values[index - window]
    )


def wilder_adx14(
    previous_high,
    previous_low,
    previous_close,
    high,
    low,
    close,
    index,
    state,
):
    """递推 Wilder ADX14；前28根K线只给出 DI，不暴露 ADX。"""
    if index < 0:
        raise ValueError("指标索引不能为负数")
    state = dict(state)
    if index == 0:
        state.update(tr14=0.0, plus_dm14=0.0, minus_dm14=0.0, dx_values=[])
        return None, None, None, state

    true_range = max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close),
    )
    upward, downward = high - previous_high, previous_low - low
    plus_dm = upward if upward > downward and upward > 0 else 0.0
    minus_dm = downward if downward > upward and downward > 0 else 0.0
    if index <= 14:
        state["tr14"] = state.get("tr14", 0.0) + true_range
        state["plus_dm14"] = state.get("plus_dm14", 0.0) + plus_dm
        state["minus_dm14"] = state.get("minus_dm14", 0.0) + minus_dm
    else:
        state["tr14"] = (state["tr14"] * 13 + true_range) / 14
        state["plus_dm14"] = (state["plus_dm14"] * 13 + plus_dm) / 14
        state["minus_dm14"] = (state["minus_dm14"] * 13 + minus_dm) / 14
    if index < 14 or state["tr14"] <= 0:
        return None, None, None, state

    plus_di = 100 * state["plus_dm14"] / state["tr14"]
    minus_di = 100 * state["minus_dm14"] / state["tr14"]
    di_total = plus_di + minus_di
    dx = 100 * abs(plus_di - minus_di) / di_total if di_total > 0 else 0.0
    if index <= 26:
        state["dx_values"] = [*state.get("dx_values", []), dx]
        return plus_di, minus_di, None, state

    if "adx" not in state:
        # 第28根K线（index == 27）集齐前14个DX值，按标准Wilder口径以算术均值作为首个ADX。
        seed = [*state.get("dx_values", []), dx]
        state["adx"] = sum(seed) / len(seed)
        return plus_di, minus_di, state["adx"], state

    state["adx"] = (state["adx"] * 13 + dx) / 14
    return plus_di, minus_di, state["adx"], state
