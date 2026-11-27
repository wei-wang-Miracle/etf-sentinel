"""统一日频回测引擎，以原始成交价格和现金分红核算资金及权益。"""

from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from itertools import pairwise
from math import sqrt
from statistics import pstdev

from app.strategies import Decision, get_strategy, validate_parameters

ENGINE_VERSION = "1.3"
CENT = Decimal("0.01")
TICK = Decimal("0.001")
ZERO = Decimal(0)


def money(value):
    """以人民币分为精度四舍五入，避免浮点累计误差。"""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def execution_price(opening, side, slip):
    """按单边滑点和最小报价单位向不利方向取整。"""
    return (
        opening * (1 + slip if side == "buy" else 1 - slip) / TICK
    ).to_integral_value(rounding=ROUND_CEILING if side == "buy" else ROUND_FLOOR) * TICK


def metrics(daily, trades, initial):
    """以期初资金为初始净值，计算含应收分红、未强平的收盘收益。"""
    values = [initial, *[Decimal(r["equity"]) for r in daily]]
    duration = (
        date.fromisoformat(daily[-1]["trade_date"])
        - date.fromisoformat(daily[0]["trade_date"])
    ).days
    total = values[-1] / initial - 1
    peak = initial
    worst = ZERO
    returns = []
    for previous, current in pairwise(values):
        peak = max(peak, current)
        worst = min(worst, current / peak - 1)
        returns.append(float(current / previous - 1))
    return {
        "total_return": float(total),
        "annual_return": float((values[-1] / initial) ** (Decimal(365) / duration) - 1)
        if duration >= 365
        else None,
        "max_drawdown": float(worst),
        "annual_volatility": pstdev(returns) * sqrt(252) if len(returns) > 1 else None,
        "trade_count": len(trades),
        "commission": str(sum((Decimal(t["commission"]) for t in trades), ZERO)),
        "slippage_cost": str(sum((Decimal(t["slippage_cost"]) for t in trades), ZERO)),
        "turnover": float(
            sum((Decimal(t["notional"]) for t in trades), ZERO) / initial
        ),
        "final_equity": str(values[-1]),
    }


def simulate(rows, dividends, settings, signals, begin, *, benchmark=False):
    """按登记日权益、除息日应收、发放日现金与次日开盘决策运行单账户。

    Args:
        rows: 已校验且包含预热数据的日行情。
        dividends: 已核实的现金分红事件，金额为每份人民币元。
        settings: 资金、成本、策略参数和日期范围。
        signals: 注册策略提供的逐日决策与通用指标。
        begin: 第一个计入账户收益的行位置。
        benchmark: 是否买入持有；同样使用本函数和相同交易成本。

    Returns:
        逐日权益、模拟成交、分红事件与统一绩效指标。
    """
    initial = Decimal(str(settings["initial_cash"]))
    rate = Decimal(str(settings["commission_rate"]))
    minimum = Decimal(str(settings["minimum_commission"]))
    slip = Decimal(str(settings["slippage_bps"])) / 10000
    cash, quantity, peak = initial, 0, initial
    entitlements, receivables = {}, {}
    daily, trades, events = [], [], []
    for i in range(begin, len(rows)):
        row = rows[i]
        day = row["trade_date"]
        if day > settings["end_date"]:
            break
        for event in dividends:
            key = event["ex_date"]
            if day == key and event["record_date"] < key:
                amount = money(
                    Decimal(entitlements.get(key, 0)) * Decimal(event["cash_per_share"])
                )
                receivables[key] = amount
                if amount:
                    events.append(
                        {
                            "trade_date": day,
                            "kind": "receivable",
                            "amount": str(amount),
                            "pay_date": event["pay_date"],
                        }
                    )
            if event["pay_date"] < day and key in receivables:
                amount = receivables.pop(key)
                cash += amount
                if amount:
                    events.append(
                        {"trade_date": day, "kind": "payment", "amount": str(amount)}
                    )
        decision = (
            Decision(1, "买入持有基准") if benchmark else signals[i - 1]["decision"]
        )
        side = (
            "buy"
            if decision.target and not quantity
            else "sell"
            if not decision.target and quantity
            else None
        )
        note = ""
        if side:
            opening = Decimal(row["open"])
            price = execution_price(opening, side, slip)
            count = quantity if side == "sell" else int(cash / (price * 100)) * 100
            if side == "buy":
                while (
                    count
                    and money(price * count) + money(max(minimum, price * count * rate))
                    > cash
                ):
                    count -= 100
            if not count:
                note = "可用资金不足一手及费用，未成交"
            else:
                notional = money(price * count)
                commission = money(max(minimum, notional * rate))
                cash += (
                    notional - commission if side == "sell" else -notional - commission
                )
                quantity += count if side == "buy" else -count
                trades.append(
                    {
                        "trade_date": day,
                        "signal_date": rows[i - 1]["trade_date"]
                        if not benchmark
                        else None,
                        "side": side,
                        "quantity": count,
                        "price": str(price),
                        "reference_open": str(opening),
                        "notional": str(notional),
                        "commission": str(commission),
                        "slippage_cost": str(money(abs(price - opening) * count)),
                        "reason": decision.reason,
                    }
                )
        for event in dividends:
            if event["record_date"] == day:
                entitlements[event["ex_date"]] = quantity
                if event["ex_date"] == day:
                    # 同日登记与除息的权益按本日收盘份额确认，不能开盘前记零。
                    amount = money(Decimal(quantity) * Decimal(event["cash_per_share"]))
                    receivables[day] = amount
                    if amount:
                        events.append(
                            {"trade_date": day, "kind": "receivable",
                             "amount": str(amount), "pay_date": event["pay_date"]}
                        )
        # 源仅提供发放日期，按当日收盘到账，不提前用于当日开盘订单。
        for event in dividends:
            key = event["ex_date"]
            if event["pay_date"] == day and key in receivables:
                amount = receivables.pop(key)
                cash += amount
                if amount:
                    events.append(
                        {"trade_date": day, "kind": "payment", "amount": str(amount)}
                    )
        pending = sum(receivables.values(), ZERO)
        equity = money(cash + Decimal(row["close"]) * quantity + pending)
        if cash < 0 or equity <= 0:
            raise ValueError("资金核算异常，停止回测")
        peak = max(peak, equity)
        next_decision = (
            Decision(1, "买入持有基准") if benchmark else signals[i]["decision"]
        )
        daily.append(
            {
                "trade_date": day,
                "cash": str(cash),
                "quantity": quantity,
                "close": row["close"],
                "market_value": str(money(Decimal(row["close"]) * quantity)),
                "dividend_receivable": str(pending),
                "equity": str(equity),
                "nav": float(equity / initial),
                "drawdown": float(equity / peak - 1),
                "position_weight": float(Decimal(row["close"]) * quantity / equity),
                "indicators": signals[i]["indicators"],
                "next_target": next_decision.target,
                "reason": next_decision.reason,
                "execution_note": note,
            }
        )
    return {
        "daily": daily,
        "trades": trades,
        "dividends": events,
        "metrics": metrics(daily, trades, initial),
    }


def run_backtest(rows, dividends, settings):
    """在相同区间和成本下运行策略与买入持有基准，不读取未知未来。

    Raises:
        ValueError: 数据范围为空、预热不足或策略未注册。
    """
    validate_parameters(settings["strategy_key"], settings["parameters"])
    rule = get_strategy(settings["strategy_key"])
    signals = rule["prepare"](rows, dividends, settings["parameters"])
    begin = next(
        (
            i
            for i, r in enumerate(rows)
            if settings["start_date"] <= r["trade_date"] <= settings["end_date"]
        ),
        None,
    )
    if begin is None:
        raise ValueError("回测范围没有行情")
    if begin < 1 or any(s["decision"] is None for s in signals[begin - 1 :]):
        raise ValueError("策略预热数据不足，请推迟开始日期或调整参数")
    if any(s["decision"].target not in (0, 1) for s in signals[begin - 1 :]):
        raise ValueError("本版仅支持空仓或满仓目标")
    return {
        "strategy": simulate(rows, dividends, settings, signals, begin),
        "benchmark": simulate(
            rows, dividends, settings, signals, begin, benchmark=True
        ),
    }
