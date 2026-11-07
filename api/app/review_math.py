"""单标的项目资金流与年化收益计算。"""

import math
from collections import defaultdict
from decimal import Decimal
from itertools import pairwise


def net_pnl(initial_asset, final_asset, flows):
    """计算区间资产变化及已含费用的买卖和分红现金流。"""
    return Decimal(final_asset) - Decimal(initial_asset) + sum(flows, Decimal(0))


def xirr(flows):
    """按自然日计算资金加权年化收益，存在潜在多解时返回空。

    Args:
        flows: 日期与金额对；投资流出为负，流入为正。

    Returns:
        唯一可验证的年化收益率；现金流不足或可能多解时返回 None。
    """
    daily = defaultdict(Decimal)
    for day, amount in flows:
        daily[day] += Decimal(amount)
    rows = [(day, amount) for day, amount in sorted(daily.items()) if amount]
    if len(rows) < 2:
        return None
    signs = [amount > 0 for _, amount in rows]
    if sum(a != b for a, b in pairwise(signs)) != 1:
        return None
    origin = rows[0][0]

    def value(log_rate):
        return sum(
            float(amount) * math.exp(-log_rate * (day - origin).days / 365)
            for day, amount in rows
        )

    low, high = -20.0, 20.0
    left, right = value(low), value(high)
    if left * right > 0:
        return None
    for _ in range(120):
        middle = (low + high) / 2
        current = value(middle)
        if current * left > 0:
            low, left = middle, current
        else:
            high = middle
    return math.expm1((low + high) / 2)
