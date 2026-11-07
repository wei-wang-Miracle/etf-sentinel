"""同一交易日历上的 ETF 原始价格比较。"""

import itertools
from decimal import Decimal


def compare_prices(series, days):
    """计算共同交易日期的价格变化；缺日或无效价格不参与排名。

    Args:
        series: 标的代码到日期、收盘价序列的映射。
        days: 所选区间的完整交易日期。

    Returns:
        每只标的的可比状态、价格变化与起点为100的价格序列。
    """
    results = {}
    for code, rows in series.items():
        values = dict(rows)
        status = "available"
        if not days or any(day not in values for day in days):
            status = "missing_dates"
        elif any(values[day] is None or Decimal(values[day]) <= 0 for day in days):
            status = "invalid_price"
        if status != "available":
            results[code] = {"status": status, "change_pct": None, "points": []}
            continue
        base = Decimal(values[days[0]])
        points = [float(Decimal(values[day]) / base * 100) for day in days]
        results[code] = {
            "status": status,
            "change_pct": float((Decimal(values[days[-1]]) / base - 1) * 100),
            "points": points,
        }
    return results


def compare_observations(series, days):
    """按共同评价日排名，源缺少末日视为过期；区间变化要求端点精确匹配。"""
    result = {}
    for code, rows in series.items():
        values = {
            day: float(value) if value is not None else None
            for day, value in rows
            if day <= days[-1]
        }
        valid = [day for day, value in values.items() if value is not None]
        last = max(valid) if valid else None
        latest = values[last] if last else None
        first, final = values.get(days[0]), values.get(days[-1])
        result[code] = {
            "latest": latest,
            "as_of": last,
            "change": final - first
            if first is not None and final is not None
            else None,
            "status": "available"
            if last == days[-1]
            else "stale"
            if last
            else "missing",
            "coverage_pct": sum(values.get(day) is not None for day in days)
            / len(days)
            * 100,
            "effective_start": min(valid) if valid else None,
            "effective_end": last,
            "points": [(str(day), values.get(day)) for day in days],
        }
    return result


def trend_statistics(rows, days):
    """计算同端点价格变化、回撤、年化波动与原始价格均线状态。"""
    from math import sqrt
    from statistics import pstdev

    result = compare_prices({"item": rows}, days)["item"]
    values = dict(rows)
    result["coverage_pct"] = sum(day in values for day in days) / len(days) * 100
    result["as_of"] = max((day for day in values if day <= days[-1]), default=None)
    if result["status"] != "available":
        return result
    closes = [float(values[day]) for day in days]
    peak, drawdowns = closes[0], []
    for close in closes:
        peak = max(peak, close)
        drawdowns.append((close / peak - 1) * 100)
    returns = [b / a - 1 for a, b in itertools.pairwise(closes)]
    history = [
        float(v) for d, v in sorted(rows) if d <= days[-1] and v is not None and v > 0
    ]
    result.update(
        max_drawdown=min(drawdowns),
        drawdowns=drawdowns,
        volatility=pstdev(returns) * sqrt(252) * 100 if len(returns) >= 2 else None,
        sample_count=len(returns),
        ma_state={
            str(w): ("高于" if closes[-1] > sum(history[-w:]) / w else "不高于")
            if len(history) >= w
            else "预热不足"
            for w in (20, 60)
        },
    )
    return result
