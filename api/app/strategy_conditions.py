"""中文条件策略的统一因果计算，供历史模拟与盘前计划复用。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import sqrt
from statistics import pstdev

from app.strategies import Decision, features

# 计算版本保持不变：旧条件公式和证据完全兼容；新增目录单独版本化。
CONDITION_VERSION = "1.0"
CATALOG_VERSION = "1.1"
EVENT_INDICATORS = {"price_cross", "ma_cross", "breakout"}
DOUBLE_WINDOW_INDICATORS = {"ma_spread", "ma_cross", "volume_ma_ratio"}
CONDITIONS = [
    {
        "key": "trend",
        "label": "含分红走势相对均线",
        "unit": "%",
        "window": True,
        "description": "含分红走势相对N日均线的偏离；0表示均线水平",
        "evidence_type": "historical",
    },
    {
        "key": "momentum",
        "label": "过去N日含息涨幅",
        "unit": "%",
        "window": True,
        "description": "当日相对N个交易日前的含息涨幅",
        "evidence_type": "historical",
    },
    {
        "key": "volatility",
        "label": "过去N日年化波动率",
        "unit": "%",
        "window": True,
        "description": "N个日含息收益总体标准差乘根号252，描述价格起伏幅度",
        "evidence_type": "historical",
    },
    {
        "key": "pe_percentile",
        "label": "指数PE本地历史分位",
        "unit": "%",
        "window": False,
        "description": "截至当日十日历年有效PE中严格低于当前值的比例",
        "evidence_type": "revised",
    },
    {
        "key": "pb_percentile",
        "label": "指数PB本地历史分位",
        "unit": "%",
        "window": False,
        "description": "截至当日十日历年有效PB中严格低于当前值的比例",
        "evidence_type": "revised",
    },
    {
        "key": "dividend_yield",
        "label": "指数股息率",
        "unit": "%",
        "window": False,
        "description": "源指数股息率；零值有效，不自动定义买卖方向",
        "evidence_type": "revised",
    },
    {
        "key": "roe",
        "label": "指数净资产收益率",
        "unit": "%",
        "window": False,
        "description": "源ROE百分数，源算法未确认，不自动定义买卖方向",
        "evidence_type": "revised",
    },
    {
        "key": "risk_premium",
        "label": "指数股债风险溢价",
        "unit": "百分点",
        "window": False,
        "description": "源股债风险溢价差值，负值有效，源算法未确认",
        "evidence_type": "revised",
    },
    {
        "key": "national_team_change",
        "label": "国家队估算比例变化",
        "unit": "百分点",
        "window": True,
        "description": "同ETF估算比例较N个交易日前变化，固定2026-01-01源基准",
        "evidence_type": "revised",
    },
    {
        "key": "sentiment",
        "label": "指定类别恐贪分数",
        "unit": "分",
        "window": False,
        "description": "显式选择的市场背景类别，0有效，不冒充ETF专属情绪",
        "evidence_type": "revised",
    },
]
CONDITIONS[0]["display_label"] = "均线乖离率"
for entry in CONDITIONS:
    entry["source"] = (
        "etf_daily"
        if entry["key"] in ("trend", "momentum", "volatility")
        else "sentiment"
        if entry["key"] == "sentiment"
        else "national_team"
        if entry["key"] == "national_team_change"
        else "index_valuation"
    )
CONDITIONS[3:3] = [
    {
        "key": key,
        "label": label,
        "unit": unit,
        "window": True,
        "description": description,
        "evidence_type": "historical",
        "source": "etf_daily",
    }
    for key, label, unit, description in [
        (
            "ma_spread",
            "双均线乖离率",
            "%",
            "含息短均线÷长均线减1；大于0表示短线高于长线",
        ),
        ("ma_slope", "均线变化率", "%", "含息N日均线相对前L个交易日同窗口均线的变化率"),
        (
            "price_cross",
            "价格穿越均线",
            "事件",
            "含息值上穿或下穿均线，仅在穿越当日成立",
        ),
        (
            "ma_cross",
            "双均线交叉",
            "事件",
            "含息短均线上穿或下穿长均线，仅在交叉当日成立",
        ),
        (
            "volume_ratio",
            "日成交量相对均量",
            "倍",
            "当日成交量÷此前N日均量，分母不含当日；不是盘中量比",
        ),
        ("volume_ma_ratio", "短长均量比", "倍", "含当日短窗口均量÷长窗口均量"),
        (
            "breakout",
            "收盘区间突破",
            "事件",
            "含息收盘值严格高于此前N日最高值或低于最低值，不含当日",
        ),
    ]
]
DEFINITIONS = {entry["key"]: entry for entry in CONDITIONS}
OPERATORS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


def validate_rule(rule):
    """校验条件及单位约束，拒绝未知字段、空条件和隐式情绪类别。

    Args:
        rule: 买卖条件组与50/100资金分配百分数。

    Raises:
        ValueError: 条件结构、阈值、窗口或类别不合法。
    """
    if not isinstance(rule, dict) or set(rule) != {"buy", "sell", "allocation"}:
        raise ValueError("规则须包含买入、卖出和投入比例")
    if type(rule["allocation"]) is not int or rule["allocation"] not in (50, 100):
        raise ValueError("投入比例只能为50或100")
    for side in ("buy", "sell"):
        group = rule[side]
        if (
            not isinstance(group, dict)
            or set(group) != {"mode", "conditions"}
            or group["mode"] not in ("all", "any")
        ):
            raise ValueError("条件组只支持全部满足或任一满足")
        if (
            not isinstance(group["conditions"], list)
            or not 1 <= len(group["conditions"]) <= 20
        ):
            raise ValueError("每组须有1至20条条件")
        for item in group["conditions"]:
            if not isinstance(item, dict) or set(item) - {
                "indicator",
                "window",
                "operator",
                "threshold",
                "category_key",
                "unit",
                "long_window",
                "lag",
            }:
                raise ValueError("条件含未支持字段")
            key = item.get("indicator")
            if (
                not isinstance(key, str)
                or key not in DEFINITIONS
                or not isinstance(item.get("operator"), str)
                or item["operator"]
                not in (
                    ("cross_up", "cross_down") if key in EVENT_INDICATORS else OPERATORS
                )
            ):
                raise ValueError("指标或比较符未注册")
            if key in DOUBLE_WINDOW_INDICATORS and (
                type(item.get("long_window")) is not int
                or type(item.get("window")) is not int
                or not item["window"] < item["long_window"] <= 250
            ):
                raise ValueError("长窗口须大于短窗口且不超过250个交易日")
            if key == "ma_slope" and (
                type(item.get("lag")) is not int or not 1 <= item["lag"] <= 250
            ):
                raise ValueError("均线方向比较间隔须为1至250个交易日的整数")
            if ("long_window" in item and key not in DOUBLE_WINDOW_INDICATORS) or (
                "lag" in item and key != "ma_slope"
            ):
                raise ValueError("指标不支持该窗口参数")
            if "unit" in item and item["unit"] != DEFINITIONS[key]["unit"]:
                raise ValueError("条件单位与指标定义不一致")
            try:
                if isinstance(item.get("threshold"), bool):
                    raise ValueError("阈值不可为布尔值")  # noqa: TRY004 — 条件输入统一转换为业务校验错误
                threshold = Decimal(str(item["threshold"]))
                if not threshold.is_finite() or abs(threshold) > 100000:
                    raise ValueError("条件阈值须为有限数值")
            except (KeyError, InvalidOperation, TypeError):
                raise ValueError("条件阈值须为有限数值") from None
            if DEFINITIONS[key]["window"] and (
                type(item.get("window")) is not int or not 2 <= item["window"] <= 250
            ):
                raise ValueError("条件窗口须为2至250个交易日的整数")
            if key == "sentiment" and (
                not isinstance(item.get("category_key"), str)
                or not item["category_key"].strip()
            ):
                raise ValueError("恐贪条件须明确选择市场背景类别")


def normalize_rule(rule):
    """保存时明确冻结每条条件的单位，避免后续将百分点误解为比例。"""
    validate_rule(rule)
    result = deepcopy(rule)
    for side in ("buy", "sell"):
        for item in result[side]["conditions"]:
            item["unit"] = DEFINITIONS[item["indicator"]]["unit"]
    return result


def external_key(item):
    """区分显式恐贪类别与ETF／关联指数指标。"""
    return (
        f"sentiment:{item['category_key']}"
        if item["indicator"] == "sentiment"
        else item["indicator"]
    )


def evidence_type(rule):
    """任何外部修订因子都会使整条规则属于修订历史研究。"""
    return (
        "revised"
        if any(
            DEFINITIONS[c["indicator"]]["evidence_type"] == "revised"
            for s in ("buy", "sell")
            for c in rule[s]["conditions"]
        )
        else "historical"
    )


def condition_warmup(item: dict) -> int:
    """返回条件首次可计算所需的收盘点数，含比较前值。"""
    key, window = item["indicator"], item.get("window", 0)
    if key in DOUBLE_WINDOW_INDICATORS:
        return item["long_window"] + (key == "ma_cross")
    if key == "ma_slope":
        return window + item["lag"]
    return window + (
        key
        in (
            "momentum",
            "volatility",
            "price_cross",
            "volume_ratio",
            "breakout",
            "national_team_change",
        )
    )


def warmup_days(rule):
    """返回各条件共同就绪所需的最长行情点数。"""
    return max(
        (condition_warmup(c) for s in ("buy", "sell") for c in rule[s]["conditions"]),
        default=1,
    )


def _micro_value(
    key: str, item: dict, i: int, values: list, averages: dict, volumes: list
) -> Fraction | None:
    """计算日K衍生值，事件依据严格比较边界返回0或1。

    Args:
        key: 新增日K指标标识。
        item: 已校验的窗口与方向参数。
        i: 当前收盘位置，禁止访问后续数据。
        values: 含息收盘序列。
        averages: 按窗口缓存的含息均线。
        volumes: 原始日成交量，缺失或负值为None。

    Returns:
        数值或事件值0/1；预热不足、缺量或零分母返回None。
    """
    if i + 1 < condition_warmup(item):
        return None
    window = item["window"]
    if key in ("ma_spread", "ma_slope"):
        numerator = averages[window][i][1]
        denominator = (
            averages[item["long_window"]][i][1]
            if key == "ma_spread"
            else averages[window][i - item["lag"]][1]
        )
        return (numerator / denominator - 1) * 100
    if key in ("price_cross", "ma_cross"):

        def difference(day: int) -> Fraction:
            """以同日含息序列计算两条线的差值。"""
            return (
                values[day] - averages[window][day][1]
                if key == "price_cross"
                else averages[window][day][1] - averages[item["long_window"]][day][1]
            )

        previous, current = difference(i - 1), difference(i)
        return Fraction(
            previous <= 0 < current
            if item["operator"] == "cross_up"
            else previous >= 0 > current
        )
    if key == "breakout":
        previous = values[i - window : i]
        return Fraction(
            values[i] > max(previous)
            if item["operator"] == "cross_up"
            else values[i] < min(previous)
        )
    long_window = item.get("long_window", window)
    previous = (
        volumes[i - window : i]
        if key == "volume_ratio"
        else volumes[i - long_window + 1 : i + 1]
    )
    current = [volumes[i]] if key == "volume_ratio" else volumes[i - window + 1 : i + 1]
    if any(v is None for v in previous + current):
        return None
    denominator = sum(previous) / len(previous)
    return (sum(current) / len(current) / denominator) if denominator > 0 else None


def prepare_conditions(rows, dividends, parameters):
    """按收盘时点逐条解释条件，持仓后仅由卖出条件决定退出。

    Args:
        rows: 含预热期的ETF原始行情，交易日升序。
        dividends: 现金分红事件，含息指标只使用当日及以前除息数据。
        parameters: rule规则、external按日期冻结的外部值、可选decision_start重置时点。

    Returns:
        引擎统一逐日决策与条件证据。任一条件未知时decision为空，不猜动作。
    """
    rule = parameters["rule"]
    validate_rule(rule)
    values = [value for value, _ in features(rows, dividends, 2)]
    prepared, holding = [], False
    returns = [float(values[i] / values[i - 1] - 1) for i in range(1, len(values))]
    averages = {}
    for side in ("buy", "sell"):
        for item in rule[side]["conditions"]:
            if item["indicator"] in (
                "trend",
                "ma_spread",
                "ma_slope",
                "price_cross",
                "ma_cross",
            ):
                for window in {item["window"], item.get("long_window", item["window"])}:
                    if window not in averages:
                        averages[window] = features(rows, dividends, window)
    volumes = [
        Fraction(str(r["volume"]))
        if r.get("volume") is not None and Decimal(str(r["volume"])) >= 0
        else None
        for r in rows
    ]
    external = parameters.get("external", {})
    for i, row in enumerate(rows):
        if row["trade_date"] == parameters.get("decision_start"):
            holding = False
        groups = {}
        ready = True
        for side in ("buy", "sell"):
            checks = []
            for item in rule[side]["conditions"]:
                key, window = item["indicator"], item.get("window", 0)
                value, evidence = None, {}
                if key == "trend":
                    average = averages[window][i][1]
                    value = (
                        (values[i] / average - 1) * 100 if average is not None else None
                    )
                elif key == "momentum":
                    value = (
                        (values[i] / values[i - window] - 1) * 100
                        if i >= window
                        else None
                    )
                elif key == "volatility":
                    value = (
                        Decimal(str(pstdev(returns[i - window : i]) * sqrt(252) * 100))
                        if i >= window
                        else None
                    )
                elif DEFINITIONS[key]["source"] == "etf_daily":
                    value = _micro_value(key, item, i, values, averages, volumes)
                else:
                    evidence = external.get(external_key(item), {}).get(
                        row["trade_date"], {}
                    )
                    raw = evidence.get("value")
                    if key == "national_team_change":
                        earlier = (
                            external.get(key, {}).get(
                                rows[i - window]["trade_date"], {}
                            )
                            if i >= window
                            else {}
                        )
                        if raw is not None and earlier.get("value") is not None:
                            value = Decimal(raw) - Decimal(earlier["value"])
                    elif raw is not None:
                        value = Decimal(str(raw))
                satisfied = (
                    bool(value)
                    if key in EVENT_INDICATORS and value is not None
                    else OPERATORS[item["operator"]](
                        value, Fraction(Decimal(str(item["threshold"])))
                    )
                    if value is not None
                    else None
                )
                ready = ready and satisfied is not None
                checks.append(
                    {
                        **item,
                        "label": DEFINITIONS[key]["label"],
                        "unit": DEFINITIONS[key]["unit"],
                        "value": (
                            str(Decimal(value.numerator) / Decimal(value.denominator))
                            if isinstance(value, Fraction)
                            else str(value)
                        )
                        if value is not None
                        else None,
                        "satisfied": satisfied,
                        "source_date": evidence.get("source_date", row["trade_date"]),
                        "collected_at": evidence.get("collected_at"),
                    }
                )
            groups[side] = checks
        if ready:
            matched = {
                side: (all if rule[side]["mode"] == "all" else any)(
                    item["satisfied"] for item in groups[side]
                )
                for side in ("buy", "sell")
            }
            holding = not matched["sell"] and (holding or matched["buy"])
        reason = (
            "条件资料或预热不足，不能判断"
            if not ready
            else "卖出条件满足，保持空仓"
            if matched["sell"]
            else "买入条件满足，目标持有"
            if matched["buy"]
            else "卖出条件未满足，继续持有"
            if holding
            else "买入条件未满足，等待"
        )
        prepared.append(
            {
                "decision": Decision(int(holding), reason) if ready else None,
                "indicators": {
                    **groups,
                    "signal_index": str(float(values[i])),
                    "evidence_type": evidence_type(rule),
                },
            }
        )
    return prepared


def condition_diagnostics(rule: dict, rows: list, signals: list, account: dict) -> dict:
    """统计可在回测区间内执行的收盘判断，区分满足天数和模拟成交。

    Args:
        rule: 本次冻结的买卖条件组。
        rows: 包含预热的升序行情。
        signals: 与行情一一对应的条件计算结果。
        account: 模拟账户，daily确定执行区间，trades为实际模拟成交。

    Returns:
        决策日区间、逐条件有效／缺失／满足天数、组满足天数及买卖笔数。
        不统计最后一天收盘后、区间内无法执行的信号。
    """
    execution_dates = {day["trade_date"] for day in account["daily"]}
    points = [
        (rows[i - 1]["trade_date"], signals[i - 1])
        for i in range(1, len(rows))
        if rows[i]["trade_date"] in execution_dates
    ]
    result = {
        "decision_start": points[0][0] if points else None,
        "decision_end": points[-1][0] if points else None,
        "days": len(points),
        "buy_trades": sum(t["side"] == "buy" for t in account["trades"]),
        "sell_trades": sum(t["side"] == "sell" for t in account["trades"]),
    }
    for side in ("buy", "sell"):
        checks = [p["indicators"][side] for _, p in points]
        ready = [
            group for group in checks if all(c["satisfied"] is not None for c in group)
        ]
        result[side] = {
            "mode": rule[side]["mode"],
            "matched_days": sum(
                (all if rule[side]["mode"] == "all" else any)(
                    c["satisfied"] for c in group
                )
                for group in ready
            ),
            "missing_days": len(checks) - len(ready),
            "conditions": [
                {
                    "label": DEFINITIONS[item["indicator"]].get(
                        "display_label", DEFINITIONS[item["indicator"]]["label"]
                    ),
                    "matched_days": sum(g[j]["satisfied"] is True for g in checks),
                    "valid_days": sum(g[j]["satisfied"] is not None for g in checks),
                    "missing_days": sum(g[j]["satisfied"] is None for g in checks),
                }
                for j, item in enumerate(rule[side]["conditions"])
            ],
        }
    return result
