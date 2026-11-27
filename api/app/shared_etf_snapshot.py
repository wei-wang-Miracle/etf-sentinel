"""共享 ETF 固定先验研究的冻结输入转换。"""

from decimal import Decimal

from app.backtest_data import (
    _decimal_text,
    _split_multiplier,
    _transition_split_multiplier,
    trading_days,
)

CORE_CODES = (
    "510180",
    "510050",
    "510300",
    "588080",
    "512100",
    "510500",
    "159915",
    "159531",
)
TRANSFER_CODES = ("518880", "515880", "560780")
SNAPSHOT_CODES = (*CORE_CODES, *TRANSFER_CODES)


def role_for_code(code):
    """返回预注册外部验证标的在冻结输入中的角色。"""
    if code in CORE_CODES:
        return "core"
    if code in TRANSFER_CODES:
        return "transfer"
    raise ValueError("标的不在固定先验外部验证范围")


def normalize_split_history(rows, actions):
    """将历史行情转换到冻结末日的统一份额口径。

    生产回测仍保留原始行情和折算事件。本函数仅为离线研究冻结输入消除
    份额变化造成的价格和成交量跳变，因此转换后的动作不再包含折算事件。
    """
    splits = actions.get("splits", [])
    factors = {}
    multiplier = Decimal(1)
    for index in range(len(rows) - 1, -1, -1):
        if index < len(rows) - 1:
            multiplier *= _transition_split_multiplier(
                splits,
                rows[index]["trade_date"],
                rows[index + 1]["trade_date"],
            )
        factors[rows[index]["trade_date"]] = multiplier

    normalized_rows = []
    for row in rows:
        factor = factors[row["trade_date"]]
        normalized = dict(row)
        for key in ("open", "high", "low", "close"):
            normalized[key] = _decimal_text(Decimal(row[key]) / factor)
        normalized["volume"] = _decimal_text(Decimal(row["volume"]) * factor)
        normalized_rows.append(normalized)

    dividends = []
    for dividend in actions.get("dividends", []):
        normalized = dict(dividend)
        factor = factors.get(dividend["ex_date"], Decimal(1))
        normalized["cash_per_share"] = _decimal_text(
            Decimal(dividend["cash_per_share"]) / factor
        )
        dividends.append(normalized)
    conversion = [
        {
            "effective_date": split["effective_date"],
            "ratio": split["ratio"],
            "share_multiplier": _decimal_text(_split_multiplier(split["ratio"])),
        }
        for split in splits
    ]
    return normalized_rows, {"dividends": dividends, "splits": []}, conversion


def validate_snapshot_rows(rows, actions):
    """校验研究冻结输入的连续交易日和基础 OHLCV 约束。"""
    if not rows:
        raise ValueError("暂无日行情")
    if actions.get("splits"):
        raise ValueError("存在未标准化的份额折算")
    days = [row["trade_date"] for row in rows]
    expected, _ = trading_days(days[0], days[-1])
    if days != expected:
        raise ValueError("行情缺少交易日、日期重复或包含非交易日")
    for row in rows:
        try:
            open_price, high, low, close = (
                Decimal(row[key]) for key in ("open", "high", "low", "close")
            )
            volume = Decimal(row["volume"])
        except (KeyError, ValueError):
            raise ValueError("行情字段缺失或非法") from None
        if (
            not all(
                value.is_finite() and value > 0
                for value in (open_price, high, low, close, volume)
            )
            or not low <= min(open_price, close) <= max(open_price, close) <= high
        ):
            raise ValueError("行情或成交量非法")


def build_snapshot_item(*, code, name, rows, actions, indices, role, source):
    """组装一只标的的研究冻结输入与可审计覆盖摘要。"""
    normalized_rows, normalized_actions, conversion = normalize_split_history(
        rows, actions
    )
    validate_snapshot_rows(normalized_rows, normalized_actions)
    return (
        {
            "name": name,
            "role": role,
            "indices": sorted(indices),
            "rows": normalized_rows,
            "actions": normalized_actions,
            "excluded_splits": [],
            "source": source,
        },
        {
            "rows": len(normalized_rows),
            "start": normalized_rows[0]["trade_date"],
            "end": normalized_rows[-1]["trade_date"],
            "normalized_splits": conversion,
        },
    )
