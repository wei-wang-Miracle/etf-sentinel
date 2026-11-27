"""新版共享原型，仅供离线研究，不改变现行策略注册和历史快照。"""

from decimal import Decimal
from statistics import fmean

from app.backtest import execution_price
from app.indicators import prior_close_margin, volume_ratio, wilder14
from app.strategies import Decision, features

VERSION = "shared-etf-research-v2.1"
RULES = {
    "range_breakout": {
        "family": "range_breakout",
        "margin": 0.2,
        "stop_atr": 2.0,
        "trail_atr": 2.5,
        "timeout": 18,
        "confirmations_required": 3,
    },
    "bottom_reversal": {"family": "bottom_reversal", "depth": 1.5, "stop_atr": 2.0},
}
FIXED_PRIOR_RULES = {
    "range_breakout": {
        "id": "range_breakout:2.0.0",
        "family": "range_breakout",
        "margin": 0.2,
        "stop_atr": 2.0,
        "trail_atr": 2.5,
        "tight_trail_atr": 1.8,
        "trail_start_atr": 2.5,
        "tighten_atr": 5.0,
        "timeout": 18,
        "timeout_gain_atr": 1.0,
        "volume_min": 1.1,
        "volume_max": 2.2,
    },
    "left_reversal": {
        "id": "left_reversal:2.0.0",
        "family": "left_reversal",
        "depth": 1.5,
        "rsi_max": 35,
        "lookback": 3,
        "stop_atr": 1.5,
        "max_stop": 0.05,
        "volume_min": 0.8,
        "volume_max": 2.5,
        "bar_position": 0.55,
        "ma_take_profit_atr": 1.5,
        "ma_trail_atr": 0.8,
    },
}
WARMUP = 64


def prepare_market(rows, dividends, events):
    """使用向前计算的含息 OHLC 尺度，计算 Wilder RSI14 和 ATR14。"""
    values = [float(value) for value, _ in features(rows, dividends, 2)]
    output, moving, volumes = [], [], [float(row["volume"]) for row in rows]
    gain = loss = atr = 0.0
    last_top = -1000
    previous_high = None
    for i, (row, value) in enumerate(zip(rows, values, strict=True)):
        previous = values[i - 1] if i else value
        scale = value / float(row["close"])
        high, low = float(row["high"]) * scale, float(row["low"]) * scale
        atr, gain, loss = wilder14(previous, value, high, low, i, atr, gain, loss)
        delta = value - previous
        rsi = (100 * gain / (gain + loss) if gain + loss else 50) if i >= 14 else None
        ma20 = fmean(values[i - 19 : i + 1]) if i >= 19 else None
        moving.append(fmean(values[i - 59 : i + 1]) if i >= 59 else None)
        if events.get(row["trade_date"]) == "top":
            last_top = i
        output.append(
            {
                "value": value,
                "scale": scale,
                "atr": atr if i >= 13 else None,
                "rsi": rsi,
                "ma20": ma20,
                "depth": (ma20 - value) / atr if ma20 is not None and atr > 0 else None,
                "margin": prior_close_margin(values, i, 20),
                "position": (value - low) / (high - low) if high > low else 0.0,
                "trend": i >= WARMUP
                and moving[i] > moving[i - 5]
                and value / moving[i] - 1 <= 0.08
                and delta <= 2.5 * atr,
                "volume_ratio": volume_ratio(volumes, i),
                "breaks_previous_high": previous_high is not None
                and value > previous_high,
                "risk": (i - last_top <= 5 or (rsi is not None and rsi >= 70))
                and delta < 0,
            }
        )
        previous_high = high
    return output


def prepare_shared(
    rows, dividends, market, rule, decision_start, *, slippage_bps=5, entry_updates=None
):
    """只替换新入场规则；收到买入目标后冻结该笔的持仓和退出规则。"""
    breakout = rule["family"] == "range_breakout"
    slip = Decimal(str(slippage_bps)) / 10000
    records = {event["record_date"]: event for event in dividends}
    ex_dates = {event["ex_date"]: event for event in dividends}
    last_exit, entry, target = -1000, None, 0
    active_rule = entry_rule = rule
    entry_updates = entry_updates or {}
    result = []
    for i, (row, bar) in enumerate(zip(rows, market, strict=True)):
        active_rule = entry_updates.get(i, active_rule)
        checks = {
            "preheated": i >= max(WARMUP, decision_start),
            "volatility": bool(bar["atr"]),
        }
        trace = {"gates": checks}
        if not checks["preheated"]:
            result.append({"decision": None, "indicators": trace})
            continue
        day = row["trade_date"]
        if target and entry is None:
            signal = market[i - 1]
            price = float(execution_price(Decimal(row["open"]), "buy", slip))
            entry_atr = signal["atr"] / signal["scale"]
            initial_stop = price - min(0.07 * price, entry_rule["stop_atr"] * entry_atr)
            protection = initial_stop
            entry = i
            peak, credited, owned = price, 0.0, set()
        elif not target and entry is not None:
            entry, last_exit = None, i
        if entry is not None:
            if event := records.get(day):
                owned.add(event["ex_date"])
            if day in owned:
                credited += float(ex_dates[day]["cash_per_share"])
            effective = float(row["close"]) + credited
            peak = max(peak, effective)
            reasons = []
            if breakout and peak - price >= 2.5 * entry_atr:
                multiplier = entry_rule["trail_atr"]
                if peak - price >= 5 * entry_atr:
                    multiplier = min(multiplier, 1.8)
                if bar["risk"]:
                    multiplier = min(multiplier, 1.2)
                protection = max(
                    protection, price, peak - multiplier * bar["atr"] / bar["scale"]
                )
            if effective <= protection:
                reasons.append(
                    "ATR移动退出" if protection > initial_stop else "ATR初始止损"
                )
            if (
                breakout
                and i - entry + 1 >= entry_rule["timeout"]
                and effective - price < entry_atr
            ):
                reasons.append("弱势时间退出")
            if not breakout and bar["value"] >= bar["ma20"]:
                reasons.append("回归MA20")
            target = int(not reasons)
            reason = "共享卖出：" + "、".join(reasons) if reasons else "继续持有"
            trace.update(
                entry_price=price,
                protection=protection,
                peak=peak,
                effective_close=effective,
                entry_atr=entry_atr,
                entry_rule=entry_rule,
            )
        else:
            checks.update(cooldown=i - last_exit > 3)
            if breakout:
                checks["no_exit_risk"] = not bar["risk"]
                trigger = bar["margin"] > active_rule["margin"] * bar["atr"]
                confirmations = {
                    "trend": bar["trend"],
                    "bar_quality": bar["position"] >= 0.6,
                    "volume": 1.1 <= bar["volume_ratio"] <= 2.5,
                }
                required = active_rule["confirmations_required"]
            else:
                prior_oversold = any(
                    (p["depth"] is not None and p["depth"] >= active_rule["depth"])
                    or p["rsi"] <= 35
                    for p in market[i - 3 : i]
                )
                trigger = prior_oversold and bar["breaks_previous_high"]
                confirmations = {
                    "below_target": bar["value"] < bar["ma20"],
                    "volume": 0.8 <= bar["volume_ratio"] <= 2.5,
                }
                required = len(confirmations)
            trace.update(
                trigger=trigger,
                confirmations=confirmations,
                required_confirmations=required,
            )
            target = int(
                all(checks.values())
                and trigger
                and sum(confirmations.values()) >= required
            )
            if target:
                entry_rule = active_rule
                trace["entry_rule"] = entry_rule
            reason = "共享买入：闸门、触发与确认数达标" if target else "等待入场条件"
        result.append({"decision": Decision(target, reason), "indicators": trace})
    return result


def prepare_fixed_prior(
    rows, dividends, market, rule, decision_start, *, slippage_bps=5
):
    """生成固定先验研究信号；不替换滚动寻优和已注册策略。"""
    breakout = rule["family"] == "range_breakout"
    slip = Decimal(str(slippage_bps)) / 10000
    records = {event["record_date"]: event for event in dividends}
    ex_dates = {event["ex_date"]: event for event in dividends}
    last_exit, entry, target = -1000, None, 0
    result = []
    for i, (row, bar) in enumerate(zip(rows, market, strict=True)):
        checks = {
            "preheated": i >= max(WARMUP, decision_start),
            "volatility": bool(bar["atr"]),
        }
        trace = {"gates": checks}
        if not checks["preheated"]:
            result.append({"decision": None, "indicators": trace})
            continue
        day = row["trade_date"]
        if target and entry is None:
            signal = market[i - 1]
            price = float(execution_price(Decimal(row["open"]), "buy", slip))
            entry_atr = signal["atr"] / signal["scale"]
            if breakout:
                initial_stop = price - min(0.07 * price, rule["stop_atr"] * entry_atr)
            else:
                structural_low = min(
                    float(point["low"]) for point in rows[max(0, i - 3) : i]
                )
                initial_stop = max(
                    price * (1 - rule["max_stop"]),
                    min(price - rule["stop_atr"] * entry_atr, structural_low),
                )
            protection = initial_stop
            entry = i
            peak, credited, owned = price, 0.0, set()
        elif not target and entry is not None:
            entry, last_exit = None, i
        if entry is not None:
            if event := records.get(day):
                owned.add(event["ex_date"])
            if day in owned:
                credited += float(ex_dates[day]["cash_per_share"])
            effective = float(row["close"]) + credited
            peak = max(peak, effective)
            reasons = []
            ma20_tightened = False
            if breakout and peak - price >= rule["trail_start_atr"] * entry_atr:
                multiplier = rule["trail_atr"]
                if peak - price >= rule["tighten_atr"] * entry_atr:
                    multiplier = rule["tight_trail_atr"]
                if bar["risk"]:
                    multiplier = min(multiplier, 1.2)
                protection = max(
                    protection, price, peak - multiplier * bar["atr"] / bar["scale"]
                )
            if not breakout and bar["value"] >= bar["ma20"]:
                if effective - price >= rule["ma_take_profit_atr"] * entry_atr:
                    reasons.append("MA20目标止盈")
                else:
                    protection = max(
                        protection,
                        price,
                        effective - rule["ma_trail_atr"] * bar["atr"] / bar["scale"],
                    )
                    ma20_tightened = True
            if effective <= protection:
                reasons.append(
                    "ATR移动退出" if protection > initial_stop else "ATR初始止损"
                )
            if (
                breakout
                and i - entry + 1 >= rule["timeout"]
                and effective - price < rule["timeout_gain_atr"] * entry_atr
            ):
                reasons.append("弱势时间退出")
            target = int(not reasons)
            reason = "共享卖出：" + "、".join(reasons) if reasons else "继续持有"
            trace.update(
                entry_price=price,
                protection=protection,
                peak=peak,
                effective_close=effective,
                entry_atr=entry_atr,
                entry_rule=rule,
                ma20_tightened=ma20_tightened,
            )
        else:
            checks.update(cooldown=i - last_exit > 3)
            if breakout:
                checks["no_exit_risk"] = not bar["risk"]
                trigger = bar["margin"] > rule["margin"] * bar["atr"]
                confirmations = {
                    "trend": bar["trend"],
                    "bar_quality": bar["position"] >= 0.6,
                    "volume": rule["volume_min"]
                    <= bar["volume_ratio"]
                    <= rule["volume_max"],
                }
            else:
                prior_oversold = any(
                    (point["depth"] is not None and point["depth"] >= rule["depth"])
                    or point["rsi"] <= rule["rsi_max"]
                    for point in market[max(0, i - rule["lookback"]) : i]
                )
                trigger = prior_oversold and bar["breaks_previous_high"]
                confirmations = {
                    "below_target": bar["value"] < bar["ma20"],
                    "volume": rule["volume_min"]
                    <= bar["volume_ratio"]
                    <= rule["volume_max"],
                    "bar_quality": bar["position"] >= rule["bar_position"],
                }
            trace.update(trigger=trigger, confirmations=confirmations)
            target = int(
                all(checks.values()) and trigger and all(confirmations.values())
            )
            if target:
                trace["entry_rule"] = rule
            reason = "共享买入：固定先验条件达标" if target else "等待入场条件"
        result.append({"decision": Decision(target, reason), "indicators": trace})
    return result
