"""供研究界面观察的因子事件；算法规则仍由服务端代码负责。"""

from statistics import fmean, pstdev

from app.indicators import (
    consecutive_down_count,
    drawdown_from_peak,
    excess_return,
    prior_close_margin,
    rolling_sma,
    volume_ratio,
    wilder14,
    wilder_adx14,
)
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
    "close_above_prior_high": {
        "name": "收盘收复昨高",
        "category": "反转确认",
        "output_type": "event",
        "meaning": "含息收盘价严格高于前一交易日最高价。",
    },
    "recovery_volume_band": {
        "name": "温和量能带",
        "category": "反转确认",
        "output_type": "state",
        "meaning": "当日成交量为此前20日均量的0.8至2.5倍，过滤极端缩量和放量。",
    },
    "below_ma20": {
        "name": "仍在MA20下方",
        "category": "均线位置",
        "output_type": "state",
        "meaning": "含息收盘价低于当日MA20。",
    },
    "close_position_positive": {
        "name": "收盘位于振幅上半区",
        "category": "价格确认",
        "output_type": "event",
        "meaning": "当日有有效振幅，且收盘位于高低价区间55%或以上。",
    },
    "lower_shadow_support": {
        "name": "长下影承接",
        "category": "反转确认",
        "output_type": "event",
        "meaning": "当日下影线至少占振幅40%，且收盘位于振幅上半区。",
    },
    "atr_overbought": {
        "name": "ATR归一化超买",
        "category": "兑现状态",
        "output_type": "state",
        "meaning": "含息收盘价高于MA20达到2.0倍Wilder ATR14。",
    },
    "wilder_rsi_overbought_turn_down": {
        "name": "Wilder RSI 超买转弱",
        "category": "兑现确认",
        "output_type": "event",
        "meaning": "Wilder RSI14此前不低于70，本日首次较前日回落。",
    },
    "close_cross_ma10_down": {
        "name": "收盘下破MA10",
        "category": "趋势走弱",
        "output_type": "event",
        "meaning": "含息收盘价从MA10上方或相等位置下穿至下方。",
    },
    "ma5_cross_ma10_down": {
        "name": "MA5下穿MA10",
        "category": "趋势走弱",
        "output_type": "event",
        "meaning": "MA5从MA10上方或相等位置下穿至下方。",
    },
    "ma5_cross_ma20_down": {
        "name": "MA5下穿MA20",
        "category": "趋势走弱",
        "output_type": "event",
        "meaning": "MA5从MA20上方或相等位置下穿至下方。",
    },
    "high_volume_stall": {
        "name": "放量高位受阻",
        "category": "兑现确认",
        "output_type": "event",
        "meaning": "日内高点超过MA20一倍ATR、成交量至少为20日均量1.5倍，且收盘转弱。",
    },
    "upper_shadow_rejection": {
        "name": "长上影受阻",
        "category": "兑现确认",
        "output_type": "event",
        "meaning": "当日上影线至少占振幅40%，且收盘位于振幅下半区。",
    },
    "atr_volatility_high": {
        "name": "ATR相对波动高位",
        "category": "波动率状态",
        "output_type": "state",
        "meaning": "ATR14/收盘价位于截至当日最近252日的80%分位或以上。",
    },
    "volatility_contracting": {
        "name": "短波动率收敛",
        "category": "波动率状态",
        "output_type": "state",
        "meaning": "20日收益波动率不高于60日收益波动率的80%。",
    },
    "volatility_expanding": {
        "name": "短波动率扩张",
        "category": "波动率状态",
        "output_type": "state",
        "meaning": "20日收益波动率不低于60日收益波动率的120%。",
    },
    "ma20_ma60_bullish": {
        "name": "MA20–MA60强势多头排列",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "MA20比MA60至少高出1.0倍Wilder ATR14。",
    },
    "trend_pullback_near_ma20": {
        "name": "上升趋势回踩MA20",
        "category": "趋势回踩",
        "output_type": "state",
        "meaning": "MA60向上，且含息收盘价距MA20不超过0.5倍Wilder ATR14。",
    },
    "valuation_low_percentile": {
        "name": "关联指数低估值保护",
        "category": "外部估值",
        "output_type": "state",
        "meaning": "关联指数此前最近可得PE或PB本地回看分位不高于30%。",
    },
    "valuation_high_percentile": {
        "name": "关联指数高估风险",
        "category": "外部估值",
        "output_type": "state",
        "meaning": "关联指数此前最近可得PE或PB本地回看分位不低于80%。",
    },
    "erp_high_percentile": {
        "name": "股债高性价比保护",
        "category": "外部估值",
        "output_type": "state",
        "meaning": "关联指数此前最近可得股债风险溢价本地回看分位不低于70%。",
    },
    "erp_low_percentile": {
        "name": "股债性价比偏低",
        "category": "外部估值",
        "output_type": "state",
        "meaning": "关联指数此前最近可得股债风险溢价本地回看分位不高于20%。",
    },
    "dividend_yield_high": {
        "name": "高股息率保护",
        "category": "外部估值",
        "output_type": "state",
        "meaning": "关联指数此前最近可得股息率本地回看分位不低于70%。",
    },
    "above_ma250": {
        "name": "年线多头区间",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "含息收盘价严格高于当日MA250；不足250根交易日不标记。",
    },
    "ma120_rising": {
        "name": "半年线向上",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "当日MA120严格高于五个交易日前；不足125根交易日不标记。",
    },
    "adx_trending": {
        "name": "趋势形成状态",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "Wilder ADX14不低于25，且+DI14高于-DI14。",
    },
    "adx_choppy": {
        "name": "无趋势震荡状态",
        "category": "趋势状态",
        "output_type": "state",
        "meaning": "Wilder ADX14低于18，表示价格方向性不足。",
    },
    "deep_drawdown_60d": {
        "name": "60日深度回撤状态",
        "category": "超跌状态",
        "output_type": "state",
        "meaning": "含息收盘相对60日内最高收盘回撤10%至35%。",
    },
    "consecutive_down_exhaustion": {
        "name": "连跌耗竭观察",
        "category": "超跌状态",
        "output_type": "state",
        "meaning": "含息收盘连续下跌不少于4个交易日。",
    },
    "gap_up_strong": {
        "name": "强势跳空高开",
        "category": "突破确认",
        "output_type": "event",
        "meaning": "当日低点较昨高跳空至少0.3倍ATR14，且收盘位于有效振幅上半区。",
    },
    "relative_strength_20d_positive": {
        "name": "相对沪深300跑赢",
        "category": "相对强弱",
        "output_type": "state",
        "meaning": "若本地沪深300指数同日序列完整，ETF过去20日含息收益至少跑赢1.5个百分点。",
    },
    "market_fear_extreme": {
        "name": "全市场极度恐惧",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得全市场恐贪总分不高于25。",
    },
    "market_greed_extreme": {
        "name": "全市场极度贪婪",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得全市场恐贪总分不低于75。",
    },
    "market_ivix_high": {
        "name": "50ETF波指高位",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得50ETF期权波动率不低于22，或本地历史样本充足时处于高分位。",
    },
    "market_ivix_calm": {
        "name": "50ETF波指低波平稳",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得50ETF期权波动率不高于16，且未出现快速上升。",
    },
    "market_breadth_weak": {
        "name": "全A创新高广度极弱",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得创新高个股占比不高于1%。",
    },
    "market_futures_deep_discount": {
        "name": "股指期货深度贴水",
        "category": "全市场环境",
        "output_type": "state",
        "meaning": "此前最近可得沪深300股指期货年化升贴水率不高于-10%。",
    },
    "sentiment_extreme_fear": {
        "name": "行业极度恐惧",
        "category": "外部情绪",
        "output_type": "state",
        "meaning": "已映射行业此前最近可得恐贪分数不高于20。",
    },
    "sentiment_fear_rebound": {
        "name": "行业恐惧回升",
        "category": "外部情绪",
        "output_type": "event",
        "meaning": "已映射行业恐贪分数此前处于极度恐惧后首次回升。",
    },
    "sentiment_extreme_greed": {
        "name": "行业极度贪婪",
        "category": "外部情绪",
        "output_type": "state",
        "meaning": "已映射行业此前最近可得恐贪分数不低于80。",
    },
}

EXTERNAL_FACTOR_IDS = frozenset(
    {
        "valuation_low_percentile",
        "valuation_high_percentile",
        "erp_high_percentile",
        "erp_low_percentile",
        "dividend_yield_high",
        "sentiment_extreme_fear",
        "sentiment_fear_rebound",
        "sentiment_extreme_greed",
        "market_fear_extreme",
        "market_greed_extreme",
        "market_ivix_high",
        "market_ivix_calm",
        "market_breadth_weak",
        "market_futures_deep_discount",
    }
)

STRATEGIES = {
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
        "description": "离线评估ATR归一化超跌、收复昨高、量能和价格承接，不可采用。",
        "research_only": True,
        "factors": (
            ("atr_oversold", "trigger"),
            ("wilder_rsi_oversold", "trigger"),
            ("close_above_prior_high", "confirmation"),
            ("recovery_volume_band", "confirmation"),
            ("lower_shadow_support", "confirmation"),
        ),
    },
}

BOX_WINDOW = 20
VOLUME_WINDOW = 20
OVERSOLD_ATR = 1.5
OVERBOUGHT_ATR = 2.0
BREAKOUT_VOLUME_MIN = 1.1
RECOVERY_VOLUME_RANGE = (0.8, 2.5)
RECOVERY_POSITION_MIN = 0.55
LOWER_SHADOW_MIN = 0.4
UPPER_SHADOW_MIN = 0.4
HIGH_VOLUME_STALL_MIN = 1.5
HIGH_VOLATILITY_PERCENTILE = 0.8
VOLATILITY_WINDOW_SHORT = 20
VOLATILITY_WINDOW_LONG = 60
VOLATILITY_CONTRACTING_RATIO = 0.8
VOLATILITY_EXPANDING_RATIO = 1.2
TREND_STRENGTH_ATR = 1.0
PULLBACK_DISTANCE_ATR = 0.5
ADX_TRENDING_MIN = 25.0
ADX_CHOPPY_MAX = 18.0
DEEP_DRAWDOWN_MIN = -0.35
DEEP_DRAWDOWN_MAX = -0.10
CONSECUTIVE_DOWN_MIN = 4
GAP_UP_ATR_MIN = 0.3
RELATIVE_STRENGTH_WINDOW = 20
RELATIVE_STRENGTH_MIN = 0.015


def _percentile(values, ratio):
    """返回升序样本的线性分位数；调用方只提供当日及以前的有限样本。"""
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _external_truth_rows(rows, external_truth):
    """核验外部真值与行情同日对齐，缺失上下文不把因子当作有效信号。"""
    if external_truth is None:
        return [{factor_id: False for factor_id in EXTERNAL_FACTOR_IDS} for _ in rows]
    if len(external_truth) != len(rows):
        raise ValueError("外部因子真值与行情长度不一致")
    output = []
    for row, truth in zip(rows, external_truth, strict=True):
        if truth.get("trade_date") != row["trade_date"]:
            raise ValueError("外部因子真值日期与行情不一致")
        output.append({factor_id: bool(truth.get(factor_id, False)) for factor_id in EXTERNAL_FACTOR_IDS})
    return output


def factor_truth_rows(
    rows,
    turning,
    dividends=(),
    external_truth=None,
    benchmark_rows=None,
):
    """对升序行情计算逐日因子真值，供离线策略研究组合既有因子。"""
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
    ma10 = [
        fmean(values[index - 9 : index + 1]) if index >= 9 else None
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
    ma120 = [rolling_sma(values, index, 120) for index in range(len(values))]
    ma250 = [rolling_sma(values, index, 250) for index in range(len(values))]

    atrs, rsis, adxs, plus_dis, minus_dis = [], [], [], [], []
    atr = gain = loss = 0.0
    adx_state = {}
    for index, row in enumerate(rows):
        value = values[index]
        previous = values[index - 1] if index else value
        atr, gain, loss = wilder14(
            previous, value, highs[index], lows[index], index, atr, gain, loss
        )
        atrs.append(atr)
        rsis.append(
            100 * gain / (gain + loss)
            if index >= 14 and gain + loss > 0
            else None
        )
        previous_high = highs[index - 1] if index else highs[index]
        previous_low = lows[index - 1] if index else lows[index]
        plus_di, minus_di, adx, adx_state = wilder_adx14(
            previous_high,
            previous_low,
            previous,
            highs[index],
            lows[index],
            value,
            index,
            adx_state,
        )
        plus_dis.append(plus_di)
        minus_dis.append(minus_di)
        adxs.append(adx)

    benchmark_by_date = {
        str(item["trade_date"]): float(item["close"])
        for item in (benchmark_rows or ())
        if item.get("trade_date") is not None and item.get("close") is not None
    }
    benchmark_values = [benchmark_by_date.get(row["trade_date"]) for row in rows]

    external_rows = _external_truth_rows(rows, external_truth)
    returns = [
        values[index] / values[index - 1] - 1 if index else 0.0
        for index in range(len(values))
    ]
    output, oversold = [], []
    for index, row in enumerate(rows):
        day = row["trade_date"]
        value = values[index]
        atr = atrs[index]
        truth = {factor_id: False for factor_id in FACTORS}
        truth.update(external_rows[index])
        if kind := turning.get(day):
            truth["turning_bottom" if kind == "bottom" else "turning_top"] = True

        truth["ma5_cross_ma20_up"] = (
            index >= 20
            and ma5[index] is not None
            and ma20[index] is not None
            and ma5[index - 1] <= ma20[index - 1]
            and ma5[index] > ma20[index]
        )
        truth["ma5_cross_ma10_down"] = (
            index >= 10
            and ma5[index - 1] is not None
            and ma10[index - 1] is not None
            and ma5[index] <= ma10[index]
            and ma5[index - 1] >= ma10[index - 1]
        )
        truth["ma5_cross_ma20_down"] = (
            index >= 20
            and ma5[index - 1] is not None
            and ma20[index - 1] is not None
            and ma5[index] <= ma20[index]
            and ma5[index - 1] >= ma20[index - 1]
        )

        margin = prior_close_margin(values, index, BOX_WINDOW)
        breakout = margin is not None and margin > 0
        truth["box_breakout_up"] = breakout

        ratio = volume_ratio(volumes, index, VOLUME_WINDOW)
        truth["volume_breakout_up"] = (
            breakout and ratio is not None and ratio >= BREAKOUT_VOLUME_MIN
        )
        truth["atr_box_breakout"] = breakout and atr > 0 and margin > 0.2 * atr

        atr_oversold = (
            ma20[index] is not None
            and atr > 0
            and (ma20[index] - value) / atr >= OVERSOLD_ATR
        )
        rsi_oversold = (
            rsis[index] is not None and rsis[index] <= 35
        )
        truth["atr_oversold"] = atr_oversold
        truth["wilder_rsi_oversold"] = rsi_oversold
        truth["ma60_rising"] = index >= 64 and ma60[index] > ma60[index - 5]
        truth["above_ma250"] = ma250[index] is not None and value > ma250[index]
        truth["ma120_rising"] = (
            index >= 124
            and ma120[index] is not None
            and ma120[index - 5] is not None
            and ma120[index] > ma120[index - 5]
        )
        truth["adx_trending"] = (
            adxs[index] is not None
            and plus_dis[index] is not None
            and minus_dis[index] is not None
            and adxs[index] >= ADX_TRENDING_MIN
            and plus_dis[index] > minus_dis[index]
        )
        truth["adx_choppy"] = adxs[index] is not None and adxs[index] < ADX_CHOPPY_MAX
        drawdown = drawdown_from_peak(values, index, 60)
        truth["deep_drawdown_60d"] = (
            index >= 59
            and drawdown is not None
            and DEEP_DRAWDOWN_MIN <= drawdown <= DEEP_DRAWDOWN_MAX
        )
        truth["consecutive_down_exhaustion"] = (
            consecutive_down_count(values, index) >= CONSECUTIVE_DOWN_MIN
        )

        position = (
            (value - lows[index]) / (highs[index] - lows[index])
            if highs[index] > lows[index]
            else 0
        )
        truth["strong_close"] = index >= 20 and position >= 0.6
        truth["gap_up_strong"] = (
            index >= 1
            and atr > 0
            and lows[index] - highs[index - 1] >= GAP_UP_ATR_MIN * atr
            and position >= 0.5
        )
        truth["relative_strength_20d_positive"] = (
            benchmark_values[index] is not None
            and index >= RELATIVE_STRENGTH_WINDOW
            and benchmark_values[index - RELATIVE_STRENGTH_WINDOW] is not None
            and excess_return(
                values,
                benchmark_values,
                index,
                RELATIVE_STRENGTH_WINDOW,
            )
            >= RELATIVE_STRENGTH_MIN
        )
        truth["close_above_prior_high"] = index >= 1 and value > highs[index - 1]
        truth["recovery_volume_band"] = (
            ratio is not None
            and RECOVERY_VOLUME_RANGE[0] <= ratio <= RECOVERY_VOLUME_RANGE[1]
        )
        truth["below_ma20"] = ma20[index] is not None and value < ma20[index]
        truth["close_position_positive"] = position >= RECOVERY_POSITION_MIN
        truth["oversold_recovery"] = (
            any(oversold[-3:])
            and truth["close_above_prior_high"]
            and truth["below_ma20"]
            and truth["recovery_volume_band"]
            and truth["close_position_positive"]
        )
        oversold.append(atr_oversold or rsi_oversold)
        price_range = highs[index] - lows[index]
        lower_shadow = min(float(row["open"]) * scale[index], value) - lows[index]
        upper_shadow = highs[index] - max(float(row["open"]) * scale[index], value)
        truth["lower_shadow_support"] = (
            price_range > 0
            and lower_shadow / price_range >= LOWER_SHADOW_MIN
            and position >= RECOVERY_POSITION_MIN
        )
        truth["atr_overbought"] = (
            ma20[index] is not None
            and atr > 0
            and (value - ma20[index]) / atr >= OVERBOUGHT_ATR
        )
        truth["wilder_rsi_overbought_turn_down"] = (
            index >= 16
            and rsis[index] is not None
            and rsis[index - 1] is not None
            and rsis[index - 2] is not None
            and rsis[index - 1] >= 70
            and rsis[index] < rsis[index - 1]
            and rsis[index - 1] >= rsis[index - 2]
        )
        truth["close_cross_ma10_down"] = (
            index >= 10
            and ma10[index - 1] is not None
            and value < ma10[index]
            and values[index - 1] >= ma10[index - 1]
        )
        truth["high_volume_stall"] = (
            ma20[index] is not None
            and atr > 0
            and highs[index] >= ma20[index] + atr
            and ratio is not None
            and ratio >= HIGH_VOLUME_STALL_MIN
            and (value <= float(row["open"]) * scale[index] or position < 0.5)
        )
        truth["upper_shadow_rejection"] = (
            price_range > 0
            and upper_shadow / price_range >= UPPER_SHADOW_MIN
            and position < 0.5
        )
        if index >= 251:
            atr_ratios = [
                prior_atr / prior_value
                for prior_atr, prior_value in zip(
                    atrs[index - 251 : index + 1], values[index - 251 : index + 1], strict=True
                )
            ]
            truth["atr_volatility_high"] = (
                atr / value >= _percentile(atr_ratios, HIGH_VOLATILITY_PERCENTILE)
            )
        if index >= VOLATILITY_WINDOW_LONG:
            short_volatility = pstdev(
                returns[index - VOLATILITY_WINDOW_SHORT + 1 : index + 1]
            )
            long_volatility = pstdev(
                returns[index - VOLATILITY_WINDOW_LONG + 1 : index + 1]
            )
            if long_volatility > 0:
                volatility_ratio = short_volatility / long_volatility
                truth["volatility_contracting"] = (
                    volatility_ratio <= VOLATILITY_CONTRACTING_RATIO
                )
                truth["volatility_expanding"] = (
                    volatility_ratio >= VOLATILITY_EXPANDING_RATIO
                )
        truth["ma20_ma60_bullish"] = (
            ma20[index] is not None
            and ma60[index] is not None
            and atr > 0
            and (ma20[index] - ma60[index]) / atr >= TREND_STRENGTH_ATR
        )
        truth["trend_pullback_near_ma20"] = (
            truth["ma60_rising"]
            and ma20[index] is not None
            and atr > 0
            and abs(value - ma20[index]) / atr <= PULLBACK_DISTANCE_ATR
        )
        output.append({"trade_date": day, **truth})

    return output


def calculate_factor_events(
    rows,
    turning,
    dividends=(),
    external_truth=None,
    benchmark_rows=None,
):
    """对升序行情计算观察事件及状态进入日。"""
    truth_rows = factor_truth_rows(
        rows,
        turning,
        dividends,
        external_truth=external_truth,
        benchmark_rows=benchmark_rows,
    )
    output, active_states = [], set()
    for truth in truth_rows:
        for factor_id, definition in FACTORS.items():
            active = truth[factor_id]
            if definition["output_type"] == "event" and active:
                output.append({"factor_id": factor_id, "trade_date": truth["trade_date"]})
            elif definition["output_type"] == "state":
                if active and factor_id not in active_states:
                    output.append({"factor_id": factor_id, "trade_date": truth["trade_date"]})
                if active:
                    active_states.add(factor_id)
                else:
                    active_states.discard(factor_id)
    return output
