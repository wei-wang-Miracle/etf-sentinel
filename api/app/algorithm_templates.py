"""共享算法模板及与回测、盘前信号共用的决策函数。"""

from datetime import date
from math import isfinite, log

from app.multifactor_research import VERSION as MULTIFACTOR_VERSION
from app.multifactor_research import build_factors, prepare_signals

TEMPLATE_ID = "etf_multifactor"
TEMPLATE_VERSION = "1.0.0"
SHARED_WARMUP_BARS = 60
TURNING_VERSION = "slope-structure-paired-v3"
TEMPLATE_STATUS = "experimental"
TEMPLATE_NOTE = "历史拟合结果不是未来胜率保证；模板不自动启用或下单。"
GROUP_NAMES = {
    "large": "大盘",
    "mid": "中盘",
    "small": "小盘",
    "micro": "微盘",
    "growth": "创业板",
    "tech": "科创板",
}

# 旧版逐ETF研究快照仅用于复盘及既有观察运行。
_LEGACY_RULES = {
    "159205": ("growth", "breakout", 20, 90, 10, 14, 30, .02, -.03, 1, 1, 5, 4, 10, 90, 3, .07, .015, .1, 15, 10, "none", 100),
    "159531": ("micro", "bottom", 5, 60, 10, 5, 35, .02, -.03, 1, .8, 5, 3, 10, 75, 2, .07, .1, .05, 20, 3, "none", 80),
    "159629": ("small", "hybrid", 5, 60, 5, 5, 35, .02, -.03, 5, .8, 0, 2, 30, 75, 2, .03, .015, .05, 40, 10, "pe_percentile", 80),
    "159845": ("small", "bottom", 5, 60, 10, 5, 35, .02, 0, 5, .8, 5, 4, 10, 75, 3, .07, .06, .05, 40, 3, "none", 80),
    "159915": ("growth", "breakout", 20, 90, 10, 5, 20, .02, -.03, 1, 1.5, 5, 2, 10, 60, 2, .07, .015, .03, 40, 10, "none", 80),
    "159919": ("large", "hybrid", 5, 60, 10, 5, 30, 0, .02, 5, 1, 10, 3, 20, 60, 3, .1, .015, .03, 30, 0, "none", 70),
    "159922": ("mid", "hybrid", 5, 90, 10, 5, 50, .01, -.05, 1, .8, 0, 3, 15, 60, 2, .04, .06, .05, 30, 20, "none", 100),
    "159952": ("growth", "hybrid", 15, 60, 10, 2, 20, .03, 0, 3, .8, 0, 4, 30, 80, 3, .07, .015, .05, 60, 5, "none", 80),
    "159977": ("growth", "pullback", 5, 60, 10, 5, 35, .02, -.03, 1, .8, 5, 3, 10, 75, 2, .07, .06, .05, 40, 20, "none", 50),
    "510050": ("large", "oversold", 3, 120, 20, 5, 40, .02, 0, 3, 1.2, 0, 2, 30, 75, 3, .05, .015, .1, 60, 20, "none", 80),
    "510180": ("large", "breakout", 5, 90, 15, 2, 35, .02, .02, 1, 1, 5, 3, 3, 60, 3, .07, .015, .1, 15, 5, "pe_percentile", 80),
    "510300": ("large", "breakout", 5, 120, 10, 2, 30, .02, -.03, 3, .8, 5, 3, 10, 80, 2, .07, .06, .05, 20, 3, "pe_percentile", 80),
    "510310": ("large", "breakout", 5, 120, 10, 14, 35, .01, -.05, 3, .8, 5, 4, 10, 60, 3, .07, .06, .05, 20, 3, "pe_percentile", 80),
    "510330": ("large", "hybrid", 5, 120, 10, 5, 40, .005, .02, 5, 1, 2, 3, 15, 75, 3, .07, .06, .03, 10, 3, "none", 80),
    "510500": ("mid", "oversold", 5, 120, 5, 14, 10, .02, .02, 5, 1, 2, 3, 10, 70, 2, .04, .06, .05, 40, 3, "none", 80),
    "512100": ("small", "bottom", 15, 40, 10, 5, 35, .02, -.03, 1, .8, 5, 3, 3, 60, 2, .03, .06, .05, 15, 3, "none", 80),
    "512500": ("mid", "hybrid", 5, 20, 10, 2, 10, 0, 0, 3, 1.5, 10, 3, 10, 75, 3, .03, .04, .03, 30, 0, "none", 100),
    "560010": ("small", "bottom", 5, 60, 10, 14, 35, .02, -.03, 1, .8, 5, 4, 10, 60, 3, .03, .06, .05, 40, 3, "none", 80),
    "588050": ("tech", "hybrid", 5, 120, 10, 5, 35, .02, .02, 5, .8, 5, 4, 10, 70, 2, .04, .1, .05, 40, 3, "none", 80),
    "588080": ("tech", "bottom", 15, 60, 10, 5, 35, .02, -.03, 5, .8, 5, 4, 10, 75, 3, .03, .1, .07, 15, 20, "none", 80),
}

_RULE_FIELDS = (
    "family", "fast", "slow", "break_window", "rsi_window", "rsi_buy",
    "dip", "trend_floor", "recovery", "volume_min", "event_age", "buy_votes",
    "exit_ma", "rsi_sell", "sell_votes", "stop_loss", "take_profit", "trailing",
    "max_holding", "cooldown", "value_metric", "value_max",
)


# 共同风控和窗口构成实验基线；每个发布版本只按模板身份取值。
_SHARED_BASE = {
    "fast": 5, "slow": 60, "break_window": 20, "rsi_window": 14,
    "rsi_buy": 35, "dip": .02, "trend_floor": -.03, "recovery": 3,
    "volume_min": .8, "event_age": 5, "buy_votes": 3, "exit_ma": 10,
    "rsi_sell": 70, "sell_votes": 2, "stop_loss": .05, "take_profit": .07,
    "trailing": .05, "max_holding": 30, "cooldown": 3,
    "value_metric": "none", "value_max": 80,
}
_SHARED_TEMPLATES = {
    ("range_breakout", "1.0.0"): (
        "箱体突破", "观察价格向上突破过去 20 个交易日区间后，趋势、修复和量能能否确认。",
        {**_SHARED_BASE, "family": "breakout", "trend_floor": 0, "volume_min": 1.2},
    ),
    ("bottom_confirmation", "1.0.0"): (
        "底部确认", "观察近 5 个交易日内是否出现底部确认，并结合价格修复、趋势和量能。",
        {**_SHARED_BASE, "family": "bottom"},
    ),
    ("hybrid_reversal", "1.0.0"): (
        "复合反转", "观察底部确认、超卖或低于均线的回落，出现任一结构后再核验修复、趋势和量能。",
        {**_SHARED_BASE, "family": "hybrid"},
    ),
}


def is_shared_template(template_id, version):
    """返回此算法版本是否允许创建回测和新绑定。"""
    return (template_id, version) in _SHARED_TEMPLATES


def template_catalog(instruments):
    """同一算法版本覆盖全部已配置ETF，具体区间仍需通过数据核验。"""
    supported = sorted(set(instruments))
    return [
        {
            "id": template_id, "version": version, "name": name,
            "status": TEMPLATE_STATUS, "description": description,
            "supported_instruments": supported, "note": TEMPLATE_NOTE,
        }
        for (template_id, version), (name, description, _) in _SHARED_TEMPLATES.items()
    ]


def template_snapshot(template_id, version, instrument_code=None):
    """共享算法快照不含ETF身份；逐ETF快照只供原有记录核验。"""
    base = {
        "id": template_id, "version": version, "status": TEMPLATE_STATUS,
        "algorithm_version": MULTIFACTOR_VERSION, "turning_version": TURNING_VERSION,
        "note": TEMPLATE_NOTE,
    }
    if shared := _SHARED_TEMPLATES.get((template_id, version)):
        name, description, rule = shared
        return {**base, "name": name, "description": description, "rule": dict(rule)}
    if template_id != TEMPLATE_ID or version != TEMPLATE_VERSION:
        raise ValueError("算法模板版本不存在")
    if instrument_code not in _LEGACY_RULES:
        raise ValueError("算法模板尚未覆盖该ETF")
    group, *values = _LEGACY_RULES[instrument_code]
    return {
        **base, "name": "ETF多因子择时（实验）", "instrument_code": instrument_code,
        "group": GROUP_NAMES[group], "rule": dict(zip(_RULE_FIELDS, values, strict=True)),
    }


def validate_template_parameters(parameters):
    """核验模板快照来自冻结目录且不含客户端算法输入。"""
    if not isinstance(parameters, dict) or set(parameters) != {
        "template", "decision_start", "external", "slippage_bps"
    }:
        raise ValueError("算法模板参数无效")
    snapshot = parameters["template"]
    if not isinstance(snapshot, dict):
        raise ValueError("算法模板快照无效")  # noqa: TRY004 — 向API统一转换为输入错误
    expected = template_snapshot(
        snapshot.get("id"), snapshot.get("version"), snapshot.get("instrument_code")
    )
    if snapshot != expected:
        raise ValueError("算法模板快照与冻结版本不一致")
    try:
        date.fromisoformat(parameters["decision_start"])
        slippage = float(parameters["slippage_bps"])
    except (TypeError, ValueError):
        raise ValueError("算法模板输入日期或滑点无效") from None
    if not isfinite(slippage) or not 0 <= slippage <= 100:
        raise ValueError("算法模板滑点须为0至100基点")
    if not isinstance(parameters["external"], dict):
        raise ValueError("算法模板估值快照无效")  # noqa: TRY004 — 向API统一转换为输入错误


def _segments(rows):
    ids, segment = [], 0
    previous = None
    for row in rows:
        values = [float(row[key]) for key in ("open", "high", "low", "close")]
        valid = all(isfinite(value) and value > 0 for value in values)
        if not valid:
            segment += 1
            ids.append(-1)
            previous = None
            continue
        day = date.fromisoformat(row["trade_date"])
        if previous is not None and (day - previous).days > 15:
            segment += 1
        ids.append(segment)
        previous = day
    return ids


def _slope(rows, volatility):
    if not volatility:
        return 0.0
    center = (len(rows) - 1) / 2
    numerator = sum((i - center) * log(float(row["close"])) for i, row in enumerate(rows))
    denominator = sum((i - center) ** 2 for i in range(len(rows)))
    return numerator / denominator / volatility


def turning_events(rows, dividends):
    """逐日移植冻结的顶底算法，返回确认日到类型的因果映射。"""
    from app.strategies import features

    signal_rows = []
    for row, (value, _) in zip(rows, features(rows, dividends, 2), strict=True):
        ratio = float(value) / float(row["close"])
        signal_rows.append({"trade_date": row["trade_date"], **{
            key: float(row[key]) * ratio for key in ("open", "high", "low", "close")
        }})
    ids = _segments(signal_rows)
    ranges, events = [], {}
    start = 0
    down_days = up_days = 0
    bottom_armed = top_armed = False
    expected = "bottom"
    last_bottom = last_top = float("-inf")
    holding_high = 0.0
    bottom = top = None
    options = {"background_days": 3, "slope_threshold": .05,
               "short_slope_threshold": .05, "breakout_window": 10,
               "breakout_atr_multiplier": .2, "confirmation_days": 1,
               "cooldown_days": 10, "confirmation_ma_window": 20}
    for i, row in enumerate(signal_rows):
        if i == 0 or ids[i] < 0 or ids[i] != ids[i - 1]:
            start = i
            down_days = up_days = 0
            bottom_armed = top_armed = False
            bottom = top = None
            holding_high = 0.0
            last_bottom = last_top = float("-inf")
        if ids[i] < 0:
            ranges.append(0.0)
            continue
        previous_close = float(signal_rows[i - 1]["close"]) if i > start else float(row["close"])
        high, low, close = (float(row[key]) for key in ("high", "low", "close"))
        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        if i - start < 59:
            continue
        atr = sum(ranges[i - 13:i + 1]) / 14
        previous_atr = sum(ranges[i - 14:i]) / 14
        slope5 = _slope(signal_rows[i - 4:i + 1], atr / close)
        slope20 = _slope(signal_rows[i - 19:i + 1], atr / close)
        previous20 = _slope(signal_rows[i - 20:i], previous_atr / previous_close)
        ma_window = options["confirmation_ma_window"]
        ma20 = sum(float(r["close"]) for r in signal_rows[i - ma_window + 1:i + 1]) / ma_window
        previous_ma20 = ma20 + (float(signal_rows[i - ma_window]["close"]) - close) / ma_window
        down_days = down_days + 1 if slope20 <= -options["slope_threshold"] else 0
        up_days = up_days + 1 if slope20 >= options["slope_threshold"] else 0
        if down_days == options["background_days"]:
            bottom_armed = True
        if up_days == options["background_days"]:
            top_armed = True
        prior = signal_rows[i - options["breakout_window"]:i]
        prior_high = max(float(r["high"]) for r in prior)
        top_prior = prior
        top_low = min(float(r["low"]) for r in top_prior)
        top_ma = sum(float(r["close"]) for r in signal_rows[i - ma_window + 1:i + 1]) / ma_window
        previous_top_ma = top_ma + (float(signal_rows[i - ma_window]["close"]) - close) / ma_window
        bottom_ready = (atr > 0 and bottom_armed and i - last_bottom >= options["cooldown_days"]
                        and slope5 > options["short_slope_threshold"] and slope20 > previous20
                        and close > ma20 and ma20 > previous_ma20)
        top_ready = (atr > 0 and top_armed and i - last_top >= options["cooldown_days"]
                     and slope5 < -options["short_slope_threshold"] and slope20 < previous20
                     and close < top_ma and top_ma < previous_top_ma)
        top_low = min(float(r["low"]) for r in top_prior)
        if expected == "top":
            holding_high = max(holding_high, high)
        if bottom and (not bottom_ready or close <= bottom["level"]):
            bottom = None
        if top and (not top_ready or close >= top["level"]):
            top = None
        signal = None
        if bottom and bottom_ready and i - bottom["index"] >= options["confirmation_days"] \
                and close > bottom["level"]:
            signal = "bottom"
            last_bottom, bottom_armed = i, False
        elif top and top_ready and i - top["index"] >= options["confirmation_days"] \
                and close < top["level"]:
            signal = "top"
            last_top, top_armed = i, False
        if not bottom and not signal and bottom_ready and close > prior_high + options["breakout_atr_multiplier"] * atr:
            bottom = {"index": i, "level": prior_high + options["breakout_atr_multiplier"] * atr}
        if not top and not signal and top_ready and close < top_low - options["breakout_atr_multiplier"] * atr:
            top = {"index": i, "level": top_low - options["breakout_atr_multiplier"] * atr}
        if signal:
            events[row["trade_date"]] = signal
            bottom = top = None
            expected = "top" if signal == "bottom" else "bottom"
            holding_high = high if signal == "bottom" else 0.0
    return events


def prepare_template(rows, dividends, parameters):
    """将冻结模板转换成统一引擎的每日收盘决策和因子解释。"""
    validate_template_parameters(parameters)
    template = parameters["template"]
    turning = turning_events(rows, dividends)
    factors = build_factors(rows, dividends, turning, parameters["external"])
    shared = is_shared_template(template["id"], template["version"])
    warmup_end = SHARED_WARMUP_BARS - 1 if shared else 60
    prepared = prepare_signals(
        rows, dividends, factors, template["rule"],
        max(warmup_end, next((i for i, row in enumerate(rows)
                              if row["trade_date"] >= parameters["decision_start"]), warmup_end)),
        slippage_bps=float(parameters["slippage_bps"]),
    )
    result = []
    model_entry_price = None
    model_state_start = parameters["decision_start"]
    for point in prepared:
        if point["indicators"].get("entry_price") is not None:
            model_entry_price = point["indicators"]["entry_price"]
        elif point["decision"] is not None and not point["decision"].target:
            model_entry_price = None
        indicators = {
            **point["indicators"],
            "model_entry_price": model_entry_price,
            "model_holding_return": point["indicators"].get("holding_return"),
            "template_version": template["version"],
            "algorithm_version": template["algorithm_version"],
            "turning_version": template["turning_version"],
            "model_state_start": model_state_start,
            "model_basis": "止损、止盈及持有期限按模拟持仓轨迹和模型参考成本计算；不代表真实持仓成本",
        }
        result.append({"decision": point["decision"], "indicators": indicators})
    return result
