"""单 ETF 真实项目复盘；不假设账户现金，不把金额曲线当净值。"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.backtest import money
from app.review_math import xirr

ZERO = Decimal(0)


def coverage_gaps(windows, start, end):
    """检查成功同步窗口的并集，返回未覆盖的自然日区间。"""
    cursor, gaps = start, []
    for left, right in sorted(windows):
        if right < cursor or left > end:
            continue
        if left > cursor:
            gaps.append((cursor, left - timedelta(days=1)))
        cursor = max(cursor, right + timedelta(days=1))
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


def calculate_actual(trades, prices, dividends, start, end):
    """从经外部准入确认的零持仓历史重建数量、成本和项目现金流。

    Args:
        trades: 完整委托累计成交，调用方已确认成交属于委托日期。
        prices: 完整日期收盘序列，须含区间前一交易日及所有成交日期。
        dividends: 已核验权益事件，现金为每份元；拆分由准入另行拦截。
        start: 复盘起日，非零期初按前一有效收盘估值。
        end: 共同截止交易日，不隐式截短。

    Returns:
        真实金额曲线、现金流、成本分解及保守的 XIRR 状态。所有费用仅扣一次。

    Raises:
        ValueError: T+1、成交金额或行情与完整历史不一致。
    """
    grouped = defaultdict(list)
    for trade in trades:
        if trade["curr_date"] <= end and trade["business_amount"] > 0:
            grouped[trade["curr_date"]].append(trade)
    price_map = dict(prices)
    if any(day not in price_map for day in grouped):
        raise ValueError("成交日期缺少交易日行情，不能重建持仓")
    quantity, cost, realized = ZERO, ZERO, ZERO
    entitlements, pending = {}, {}
    daily, flows, markers = [], [], []
    initial = None
    initial_realized = initial_unrealized = initial_entitled = ZERO
    fees = paid = entitled = ZERO
    cumulative = ZERO
    previous_asset = ZERO
    previous_day = None
    previous_close = ZERO
    ambiguous_cost = False
    first_day = prices[0][0] if prices else end
    close = ZERO
    for offset in range((end - first_day).days + 1):
        day = first_day + timedelta(days=offset)
        if day in price_map:
            close = price_map[day]
        if day >= start and initial is None:
            initial = previous_asset
            initial_realized = realized
            initial_unrealized = quantity * previous_close - cost if quantity else ZERO
            initial_entitled = entitled
            if initial:
                flows.append((previous_day, -initial))
        day_flow = ZERO
        for event in dividends:
            key = event["ex_date"]
            if key <= str(day) and key not in pending and key in entitlements:
                amount = money(entitlements.pop(key) * Decimal(event["cash_per_share"]))
                pending[key] = amount
                entitled += amount
            if event["pay_date"] <= str(day) and key in pending:
                amount = pending.pop(key)
                day_flow += amount
                if day >= start:
                    paid += amount
        rows = grouped.get(day, [])
        buys = [t for t in rows if t["entrust_side"] == "1"]
        sells = [t for t in rows if t["entrust_side"] == "2"]
        if buys and sells:
            ambiguous_cost = True
        if len(buys) + len(sells) != len(rows):
            raise ValueError("存在未确认方向的有效成交")
        if sum((t["business_amount"] for t in sells), ZERO) > quantity:
            raise ValueError("卖出超过前一日旧仓，T+1或期初持仓待核验")
        # 日级聚合先处理旧仓卖出；同日买卖不推断精确时刻。
        for trade in sells + buys:
            side, count = trade["entrust_side"], trade["business_amount"]
            balance, clear = trade["business_balance"], trade["clear_balance"]
            fee = clear - balance if side == "1" else balance - clear
            if balance <= 0 or clear <= 0 or fee < 0 or fee > balance * Decimal("0.01"):
                raise ValueError("成交或清算金额异常，推导费用待核验")
            if side == "1":
                quantity += count
                cost += clear
                day_flow -= clear
            else:
                removed = cost * count / quantity
                realized += clear - removed
                cost -= removed
                quantity -= count
                day_flow += clear
            if day >= start:
                fees += fee
        for side, entries in (("buy", buys), ("sell", sells)):
            if entries and day >= start:
                count = sum((t["business_amount"] for t in entries), ZERO)
                balance = sum((t["business_balance"] for t in entries), ZERO)
                markers.append(
                    {
                        "trade_date": str(day),
                        "side": side,
                        "quantity": str(count),
                        "price": str(balance / count),
                        "entrust_nos": [t["entrust_no"] for t in entries],
                    }
                )
        for event in dividends:
            if event["record_date"] == str(day):
                entitlements[event["ex_date"]] = quantity
        receivable = sum(pending.values(), ZERO)
        asset = quantity * close + receivable
        if day >= start:
            cumulative += day_flow
            if day_flow:
                flows.append((day, day_flow))
            if day in price_map:
                daily.append(
                    {
                        "trade_date": str(day),
                        "quantity": str(quantity),
                        "dividend_receivable": str(receivable),
                        "market_value": str(money(quantity * close)),
                        "net_pnl": str(money(asset - initial + cumulative)),
                    }
                )
        previous_asset = asset
        if day in price_map:
            previous_day, previous_close = day, close
    if not daily or initial is None:
        raise ValueError("区间没有可复盘行情")
    if previous_asset:
        flows.append((end, previous_asset))
    rate = xirr(flows)
    active = [(day, amount) for day, amount in flows if amount]
    return {
        "status": "available",
        "initial_asset": str(money(initial)),
        "final_asset": str(money(previous_asset)),
        "final_quantity": str(quantity),
        "final_receivable": str(money(sum(pending.values(), ZERO))),
        "net_pnl": daily[-1]["net_pnl"],
        "fees": str(money(fees)),
        "dividends_paid": str(money(paid)),
        "dividend_entitlement": str(money(entitled - initial_entitled)),
        "realized_pnl": str(money(realized - initial_realized))
        if not ambiguous_cost
        else None,
        "unrealized_pnl": str(
            money(quantity * price_map[end] - cost - initial_unrealized)
        )
        if not ambiguous_cost
        else None,
        "cost_decomposition_status": "同日双向累计成交无法确认成本顺序，分解不输出；现金流净盈亏不受影响"
        if ambiguous_cost
        else "平均成本，费用已计入",
        "xirr": rate,
        "xirr_status": "available"
        if rate is not None
        else "现金流不足、无解或潜在多解，不选择任意根",
        "cashflow_start": str(min(d for d, _ in active)) if active else None,
        "cashflow_end": str(max(d for d, _ in active)) if active else None,
        "cashflows": [
            {"trade_date": str(d), "amount": str(money(v))} for d, v in flows
        ],
        "daily": daily,
        "markers": markers,
        "dividend_note": "按公开权益事件推算，未核对券商到账流水；费用已计入，不再扣减",
    }
