"""供研究界面观察的因子事件；算法规则仍由服务端代码负责。"""

from statistics import fmean

from app.indicators import prior_close_margin, volume_ratio, wilder14
from app.strategies import features

FACTORS = {
    "turning_bottom": {
        "name": "阶段底部确认",
        "category": "结构确认",
        "output_type": "event",
        "meaning": "因果状态机在该交易日确认阶段底部，不代表买入信号。",
    },
    "turning_top": {
        "name": "阶段顶部确认",
        "category": "结构确认",
        "output_type": "event",
        "meaning": "因果状态机在该交易日确认阶段顶部，不代表卖出指令。",
    },
    "ma5_cross_ma20_up": {
        "name": "短均线上穿中期均线",
        "category": "趋势转折",
        "output_type": "event",
        "meaning": "MA5 从 MA20 下方上穿至上方的交易日。",
    },
    "box_breakout_up": {
        "name": "箱体向上突破",
        "category": "突破事件",
        "output_type": "event",
        "meaning": "当日含息收盘价高于此前20个交易日最高收盘价；连创新高可以连续标记。",
    },
    "volume_breakout_up": {
        "name": "放量向上突破",
        "category": "突破确认",
        "output_type": "event",
        "meaning": "向上突破同日的成交量至少为此前20日均量的1.1倍。",
    },
    "atr_oversold": {
        "name": "ATR归一化超跌",
        "category": "超跌状态",
        "output_type": "state",
        "meaning": "含息收盘价低于MA20达到1.5倍Wilder ATR14。",
    },
    "oversold_recovery": {
        "name": "超跌后止跌修复",
        "category": "反转确认",
        "output_type": "event",
        "meaning": "近期超跌后收盘突破昨高，并满足量能、收盘位置和MA20下方条件。",
    },
    "wilder_rsi_oversold": {
        "name": "Wilder RSI 超卖",
        "category": "超跌状态",
        "output_type": "state",
        "meaning": "Wilder RSI14 不高于35；只标记进入状态的首日。",
    },
    "ma60_rising": {
        "name": "MA60 向上",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "MA60 高于五个交易日前；只标记进入状态的首日。",
    },
    "strong_close": {
        "name": "日内强势收盘",
        "category": "价格确认",
        "output_type": "event",
        "meaning": "当日有有效振幅，且收盘位于当日高低价区间的60%或以上。",
    },
    "atr_box_breakout": {
        "name": "ATR 余量突破",
        "category": "突破事件",
        "output_type": "event",
        "meaning": "超过此前20日最高收盘的幅度严格大于0.2倍Wilder ATR14。",
    },
}

STRATEGIES = {
    "range_breakout": {
        "name": "箱体突破",
        "description": "观察价格向上突破过去20个交易日区间后，趋势、修复和量能能否确认。",
        "factors": (
            ("box_breakout_up", "trigger"),
            ("turning_top", "risk"),
        ),
    },
    "bottom_confirmation": {
        "name": "底部确认",
        "description": "观察阶段底部确认，并结合价格修复、趋势和量能判断。",
        "factors": (
            ("turning_bottom", "trigger"),
            ("turning_top", "risk"),
        ),
    },
    "hybrid_reversal": {
        "name": "复合反转",
        "description": "观察阶段底部或超卖结构，并等待修复、趋势和量能确认。",
        "factors": (
            ("turning_bottom", "trigger"),
            ("turning_top", "risk"),
        ),
    },
    "range_breakout_research": {
        "name": "共享突破研究",
        "description": "离线评估共享箱体突破、趋势、收盘位置和量能确认，不可采用。",
        "research_only": True,
        "factors": (
            ("atr_box_breakout", "trigger"),
            ("ma60_rising", "confirmation"),
            ("strong_close", "confirmation"),
            ("turning_top", "risk"),
        ),
    },
    "left_reversal_research": {
        "name": "左侧反转研究",
        "description": "离线评估ATR归一化超跌、短线修复和MA20回归，不可采用。",
        "research_only": True,
        "factors": (
            ("atr_oversold", "trigger"),
            ("wilder_rsi_oversold", "trigger"),
            ("oversold_recovery", "trigger"),
        ),
    },
}

BOX_WINDOW = 20
VOLUME_WINDOW = 20
OVERSOLD_ATR = 1.5
BREAKOUT_VOLUME_MIN = 1.1
RECOVERY_VOLUME_RANGE = (0.8, 2.5)
RECOVERY_POSITION_MIN = 0.55


def calculate_factor_events(rows, turning, dividends=()):
    """对升序行情计算观察事件及状态进入日。"""
    if any(kind not in ("bottom", "top") for kind in turning.values()):
        raise ValueError("顶底事件类型无效")
    if not rows:
        return []

    values = [float(value) for value, _ in features(rows, dividends, 2)]
    scale = [
        value / float(row["close"]) for value, row in zip(values, rows, strict=True)
    ]
    highs = [
        float(row["high"]) * factor for row, factor in zip(rows, scale, strict=True)
    ]
    lows = [float(row["low"]) * factor for row, factor in zip(rows, scale, strict=True)]
    volumes = [float(row["volume"]) for row in rows]
    ma5 = [
        fmean(values[index - 4 : index + 1]) if index >= 4 else None
        for index in range(len(values))
    ]
    ma20 = [
        fmean(values[index - 19 : index + 1]) if index >= 19 else None
        for index in range(len(values))
    ]
    ma60 = [
        fmean(values[index - 59 : index + 1]) if index >= 59 else None
        for index in range(len(values))
    ]

    output, states, oversold = [], set(), []
    atr = gain = loss = 0.0
    for index, row in enumerate(rows):
        day = row["trade_date"]
        value = values[index]
        previous = values[index - 1] if index else value
        atr, gain, loss = wilder14(
            previous, value, highs[index], lows[index], index, atr, gain, loss
        )
        if kind := turning.get(day):
            factor_id = "turning_bottom" if kind == "bottom" else "turning_top"
            output.append({"factor_id": factor_id, "trade_date": day})

        if (
            index >= 20
            and ma5[index] is not None
            and ma20[index] is not None
            and ma5[index - 1] <= ma20[index - 1]
            and ma5[index] > ma20[index]
        ):
            output.append({"factor_id": "ma5_cross_ma20_up", "trade_date": day})

        margin = prior_close_margin(values, index, BOX_WINDOW)
        breakout = margin is not None and margin > 0
        if breakout:
            output.append({"factor_id": "box_breakout_up", "trade_date": day})

        ratio = volume_ratio(volumes, index, VOLUME_WINDOW)
        if breakout and ratio is not None and ratio >= BREAKOUT_VOLUME_MIN:
            output.append({"factor_id": "volume_breakout_up", "trade_date": day})
        if breakout and atr > 0 and margin > 0.2 * atr:
            output.append({"factor_id": "atr_box_breakout", "trade_date": day})

        atr_oversold = (
            ma20[index] is not None
            and atr > 0
            and (ma20[index] - value) / atr >= OVERSOLD_ATR
        )
        rsi_oversold = (
            index >= 14 and gain + loss > 0 and 100 * gain / (gain + loss) <= 35
        )
        for factor_id, active in (
            ("atr_oversold", atr_oversold),
            ("wilder_rsi_oversold", rsi_oversold),
            ("ma60_rising", index >= 64 and ma60[index] > ma60[index - 5]),
        ):
            if active and factor_id not in states:
                output.append({"factor_id": factor_id, "trade_date": day})
            if active:
                states.add(factor_id)
            else:
                states.discard(factor_id)

        position = (
            (value - lows[index]) / (highs[index] - lows[index])
            if highs[index] > lows[index]
            else 0
        )
        if index >= 20 and position >= 0.6:
            output.append({"factor_id": "strong_close", "trade_date": day})
        if (
            any(oversold[-3:])
            and value > highs[index - 1]
            and ma20[index] is not None
            and value < ma20[index]
            and ratio is not None
            and RECOVERY_VOLUME_RANGE[0] <= ratio <= RECOVERY_VOLUME_RANGE[1]
            and position >= RECOVERY_POSITION_MIN
        ):
            output.append({"factor_id": "oversold_recovery", "trade_date": day})
        oversold.append(atr_oversold or rsi_oversold)

    return output
