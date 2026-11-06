"""策略注册与因果指标计算；规则不参与成交、费用或账户核算。"""

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction


@dataclass(frozen=True)
class Decision:
    """收盘决策：target为0或1目标仓位，reason为可复盘原因。"""

    target: int
    reason: str


def features(rows, dividends, window):
    """以精确有理数构造因果含息指数及均线，避免横盘等值被残差误判。

    仅使用前值、当日收盘和当日除息现金。未充分预热时均线为空；
    不用未知口径复权值，显示时才转换十进制数。
    """
    cash = {e["ex_date"]: Fraction(e["cash_per_share"]) for e in dividends}
    values, result = [], []
    total = Fraction(0)
    for i, row in enumerate(rows):
        value = (
            Fraction(100)
            if i == 0
            else (
                values[-1]
                * (Fraction(row["close"]) + cash.get(row["trade_date"], 0))
                / Fraction(rows[i - 1]["close"])
            )
        )
        values.append(value)
        total += value
        if i >= window:
            total -= values[i - window]
        result.append((value, total / window if i + 1 >= window else None))
    return result


def decide(strategy_key, value, average):
    """均线规则按精确值比较，等于均线时空仓；预热不足拒绝决策。"""
    if strategy_key != "ma_trend":
        raise ValueError("策略未注册")
    if average is None:
        raise ValueError("均线预热数据不足，请推迟开始日期或缩短均线")
    holding = value > average
    return Decision(
        int(holding),
        "含息指数高于均线，目标满仓" if holding else "含息指数不高于均线，目标空仓",
    )


def prepare_ma(rows, dividends, parameters):
    """将均线指标与规则转换为引擎通用的逐日决策和指标快照。"""

    def display(value):
        return (
            str(Decimal(value.numerator) / Decimal(value.denominator))
            if value is not None
            else None
        )

    return [
        {
            "decision": decide("ma_trend", value, average)
            if average is not None
            else None,
            "indicators": {
                "signal_index": display(value),
                "moving_average": display(average),
            },
        }
        for value, average in features(rows, dividends, parameters["window"])
    ]


REGISTRY = {
    "ma_trend": {
        "metadata": {
            "key": "ma_trend",
            "name": "均线趋势",
            "version": "1.1",
            "description": "收盘含息指数高于过去N日均线则持有，否则空仓；下一交易日开盘执行",
            "parameters": [
                {
                    "key": "window",
                    "label": "均线交易日数",
                    "default": 60,
                    "min": 2,
                    "max": 250,
                }
            ],
        },
        "prepare": prepare_ma,
    }
}


def get_strategy(key):
    """查找注册策略；未知规则不能进入统一引擎。"""
    if key not in REGISTRY:
        raise ValueError("策略未注册")
    return REGISTRY[key]


def strategy_catalog():
    """向统一页面提供已注册策略的中文名称、参数和版本。"""
    return [entry["metadata"] for entry in REGISTRY.values()]


def validate_parameters(key, parameters):
    """按注册参数约束校验，拒绝未知字段或越界值。"""
    definitions = get_strategy(key)["metadata"]["parameters"]
    if set(parameters) != {p["key"] for p in definitions}:
        raise ValueError("策略参数缺失或包含未注册参数")
    for p in definitions:
        value = parameters[p["key"]]
        if type(value) is not int or not p["min"] <= value <= p["max"]:
            raise ValueError(f"{p['label']}须为{p['min']}至{p['max']}的整数")
