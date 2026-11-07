"""中文条件策略的统一因果计算，供历史模拟与盘前计划复用。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from math import sqrt
from statistics import pstdev

from app.strategies import Decision, features

CONDITION_VERSION = "1.0"
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
            }:
                raise ValueError("条件含未支持字段")
            key = item.get("indicator")
            if (
                not isinstance(key, str)
                or key not in DEFINITIONS
                or not isinstance(item.get("operator"), str)
                or item["operator"] not in OPERATORS
            ):
                raise ValueError("指标或比较符未注册")
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


def warmup_days(rule):
    """返回最长前置窗口；动量和波动需要额外一个收盘点。"""
    return max(
        (
            c.get("window", 0) + (c["indicator"] in ("momentum", "volatility"))
            for s in ("buy", "sell")
            for c in rule[s]["conditions"]
        ),
        default=1,
    )


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
            if item["indicator"] == "trend" and item["window"] not in averages:
                averages[item["window"]] = features(rows, dividends, item["window"])
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
                    OPERATORS[item["operator"]](
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
