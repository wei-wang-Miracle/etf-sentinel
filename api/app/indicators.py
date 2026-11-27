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
