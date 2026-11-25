"""离线多因子研究：因子投票产生最终信号，成交仍由统一回测引擎执行。"""

from decimal import ROUND_CEILING, Decimal
from statistics import fmean

from app.strategies import Decision, features

VERSION = "multifactor-v1"
WINDOWS = (3, 5, 10, 15, 20, 30, 40, 60, 90, 120)
BREAK_WINDOWS = (3, 5, 10, 15, 20, 40, 60)
RSI_WINDOWS = (2, 5, 7, 14)
DEFAULT_RULE = {
    "family": "hybrid", "fast": 5, "slow": 60, "break_window": 10,
    "rsi_window": 5, "rsi_buy": 35, "dip": .02, "trend_floor": -.03,
    "recovery": 1, "volume_min": .8, "event_age": 5, "buy_votes": 3,
    "exit_ma": 10, "rsi_sell": 75, "sell_votes": 2, "stop_loss": .07,
    "take_profit": .06, "trailing": .05, "max_holding": 40, "cooldown": 3,
    "value_metric": "none", "value_max": 80,
}


def build_factors(rows, dividends, turning, external=None):
    """只读取当前及以前的含息价格、原始量和上一交易日精确估值日期。

    RSI为窗口内简单平均涨跌幅的比值，不使用Wilder平滑；突破窗口不含当日。
    顶底输入为已冻结的因果确认事件，不是事后局部极值。估值缺日保留空值。
    """
    values = [float(value) for value, _ in features(rows, dividends, 2)]
    volumes = [float(r["volume"]) for r in rows]
    result, last = [], {"bottom": -10000, "top": -10000}
    external = external or {}
    for i, row in enumerate(rows):
        if row["trade_date"] in turning:
            last[turning[row["trade_date"]]] = i
        averages = {
            w: fmean(values[i - w + 1:i + 1]) if i + 1 >= w else None
            for w in WINDOWS
        }
        rsi = {}
        for w in RSI_WINDOWS:
            changes = [values[j] - values[j - 1] for j in range(max(1, i - w + 1), i + 1)]
            gain = sum(max(0, c) for c in changes)
            loss = sum(max(0, -c) for c in changes)
            rsi[w] = (100 * gain / (gain + loss) if gain + loss else 50) if i >= w else None
        result.append({
            "signal_index": values[i], "rsi": rsi,
            "bias": {w: values[i] / avg - 1 if avg else None for w, avg in averages.items()},
            "momentum": {w: values[i] / values[i - w] - 1 if i >= w else None
                         for w in (1, 3, 5, 10, 20)},
            "break_up": {w: values[i] > max(values[i - w:i]) if i >= w else None
                         for w in BREAK_WINDOWS},
            "break_down": {w: values[i] < min(values[i - w:i]) if i >= w else None
                           for w in BREAK_WINDOWS},
            "volume_ratio": volumes[i] / fmean(volumes[i - 20:i]) if i >= 20 else None,
            "bottom_age": i - last["bottom"], "top_age": i - last["top"],
            **{key: float(raw) if (raw := external.get(key, {}).get(
                rows[i - 1]["trade_date"], {}).get("value")) is not None and i else None
               for key in ("pe_percentile", "pb_percentile")},
            "valuation_source_date": rows[i - 1]["trade_date"] if i else None,
        })
    return result


def prepare_signals(rows, dividends, factors, rule, decision_start, *, slippage_bps=5, exit_policy=None):
    """升序计算五项等权入场票和三项风险票，卖出优先于买入。

    当日开盘只执行昨日目标；收盘风险以实际模拟开盘含滑点价格及已登记
    分红权益为依据。任何退出先成为最终空仓信号，下一开盘才卖出。
    估值缺失阻止入场，但不阻止已有仓位退出。不按事后盈亏筛选信号。
    离线研究可传入退出函数，复用同一模拟持仓、分红和开盘执行口径。
    """
    target, holding, entry_index, entry_price = 0, False, 0, Decimal(0)
    credited, peak, last_exit = 0., 0., -10000
    entitlements = {}
    result = []
    for i, (row, f) in enumerate(zip(rows, factors, strict=True)):
        if target and not holding:
            entry_price = (Decimal(row["open"]) * (1 + Decimal(str(slippage_bps)) / 10000) / Decimal(".001")).to_integral_value(rounding=ROUND_CEILING) * Decimal(".001")
            holding, entry_index, credited, peak = True, i, 0., 0.
        elif not target and holding:
            holding, last_exit = False, i
        for event in dividends:
            if holding and event["record_date"] == row["trade_date"]:
                entitlements[event["ex_date"]] = entry_index
            if holding and event["ex_date"] == row["trade_date"] and entitlements.get(event["ex_date"]) == entry_index:
                credited += float(event["cash_per_share"])
        holding_return = (float(row["close"]) + credited) / float(entry_price) - 1 if holding else None
        peak = max(peak, holding_return) if holding else 0.
        ready = i >= max(59, decision_start) and all(v is not None for v in (
            f["bias"][rule["slow"]], f["bias"][rule["fast"]],
            f["bias"][rule["exit_ma"]], f["rsi"][rule["rsi_window"]],
            f["break_up"][rule["break_window"]], f["volume_ratio"],
        ))
        buy, sell, buy_score, sell_score = {}, {}, 0, 0
        reason = "预热或区间未就绪，保持空仓"
        if ready:
            bottom = f["bottom_age"] <= rule["event_age"]
            oversold = f["rsi"][rule["rsi_window"]] <= rule["rsi_buy"]
            dip = f["bias"][20] <= -rule["dip"]
            structure = {
                "bottom": bottom, "oversold": oversold or dip,
                "pullback": f["bias"][rule["fast"]] <= -rule["dip"],
                "breakout": f["break_up"][rule["break_window"]],
                "hybrid": bottom or oversold or dip,
            }[rule["family"]]
            buy = {
                "structure": bool(structure),
                "recovery": f["momentum"][rule["recovery"]] > 0,
                "trend": f["bias"][rule["slow"]] >= rule["trend_floor"],
                "volume": f["volume_ratio"] >= rule["volume_min"],
            }
            value_ready = rule["value_metric"] == "none" or f[rule["value_metric"]] is not None
            value_pass = rule["value_metric"] == "none" or (
                value_ready and f[rule["value_metric"]] <= rule["value_max"])
            if rule["value_metric"] != "none":
                buy["valuation"] = value_pass
            buy_score = sum(buy.values())
            sell = {
                "top": f["top_age"] <= rule["event_age"],
                "trend_weak": f["bias"][rule["exit_ma"]] < 0 and f["momentum"][3] < 0,
                "overbought_weak": f["rsi"][rule["rsi_window"]] >= rule["rsi_sell"] and f["momentum"][1] < 0,
            }
            sell_score = sum(sell.values())
            reason = "汇总入场不足，继续等待"
            if holding:
                if exit_policy is not None:
                    exits = exit_policy(i, entry_index, entry_price, holding_return, peak, f)
                else:
                    exits = []
                    if holding_return <= -rule["stop_loss"]:
                        exits.append("止损")
                    if holding_return >= rule["take_profit"]:
                        exits.append("止盈")
                    if peak - holding_return >= rule["trailing"]:
                        exits.append("移动退出")
                    if i - entry_index + 1 >= rule["max_holding"]:
                        exits.append("持有期限")
                    if sell_score >= rule["sell_votes"]:
                        exits.append(f"风险汇总{sell_score}票")
                target = int(not exits)
                reason = "汇总卖出：" + "、".join(exits) if exits else "继续持有，退出条件未满足"
            elif value_ready and value_pass and structure and buy_score >= rule["buy_votes"] and sell_score < rule["sell_votes"] and i - last_exit > rule["cooldown"]:
                target, reason = 1, f"汇总买入：{rule['family']}结构成立，{buy_score}票"
            elif not value_ready:
                reason = "估值源日期缺失，禁止新开仓"
        result.append({
            "decision": Decision(target, reason),
            "indicators": {"buy": buy, "sell": sell, "buy_score": buy_score,
                           "sell_score": sell_score, "holding_return": holding_return,
                           "entry_price": str(entry_price) if holding else None},
        })
    return result
