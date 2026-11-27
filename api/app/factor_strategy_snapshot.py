"""分类因子策略研究的冻结输入转换与类别目录。"""

from decimal import Decimal

from app.backtest_data import trading_days
from app.research_factor_context import build_external_factor_truth
from app.research_factors import factor_truth_rows
from app.shared_etf_snapshot import normalize_split_history

CATEGORY_BY_CODE = {
    "159919": "大盘宽基",
    "510050": "大盘宽基",
    "510180": "大盘宽基",
    "510300": "大盘宽基",
    "510310": "大盘宽基",
    "510330": "大盘宽基",
    "159922": "中盘宽基",
    "510500": "中盘宽基",
    "512500": "中盘宽基",
    "159629": "小盘宽基",
    "159845": "小盘宽基",
    "512100": "小盘宽基",
    "560010": "小盘宽基",
    "159531": "微盘",
    "159205": "创业板",
    "159915": "创业板",
    "159952": "创业板",
    "159977": "创业板",
    "588050": "科创板",
    "588080": "科创板",
    "518880": "黄金",
    "515880": "通信设备",
    "560780": "半导体材料设备",
}


def category_for_code(code):
    """返回研究报告使用的资产类别，未知代码保留为待补充分组。"""
    return CATEGORY_BY_CODE.get(code, "未分类")


def independent_key(code, indices):
    """同一关联指数共享一个评分单位，未映射资产自身独立。"""
    return indices[0] if len(indices) == 1 else code


def _validate_rows_with_suspensions(rows, actions, verified_suspensions=()):
    """校验研究快照的日历覆盖与 OHLCV 约束，仅放行经跨源核验的真实停牌日。"""
    if not rows:
        raise ValueError("暂无日行情")
    if actions.get("splits"):
        raise ValueError("存在未标准化的份额折算")
    days = [row["trade_date"] for row in rows]
    if len(days) != len(set(days)) or days != sorted(days):
        raise ValueError("行情日期重复或未按升序排列")
    expected, calendar_version = trading_days(days[0], days[-1])
    expected_set = set(expected)
    day_set = set(days)
    if not day_set <= expected_set:
        raise ValueError("行情包含非交易日")
    missing = expected_set - day_set
    allowed = set(verified_suspensions)
    unverified_missing = sorted(missing - allowed)
    if unverified_missing:
        raise ValueError(
            f"行情缺少未核验交易日（首日 {unverified_missing[0]}）"
        )
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
    return sorted(missing & allowed), calendar_version


def build_factor_snapshot_item(
    *,
    code,
    name,
    rows,
    actions,
    indices,
    source,
    turning,
    start_date=None,
    verified_suspensions=(),
    factor_context=None,
):
    """构造标准化行情、因子逐日真值及类别元数据的一只研究标的。"""
    sliced_rows = (
        [row for row in rows if row["trade_date"] >= str(start_date)]
        if start_date
        else list(rows)
    )
    if not sliced_rows:
        raise ValueError(f"{code} 在 {start_date} 之后无有效行情")
    window_first = sliced_rows[0]["trade_date"]
    sliced_actions = {
        "dividends": [
            event
            for event in actions.get("dividends", [])
            if event["ex_date"] >= window_first
        ],
        "splits": [
            event
            for event in actions.get("splits", [])
            if event["effective_date"] >= window_first
        ],
    }
    normalized_rows, normalized_actions, conversion = normalize_split_history(
        sliced_rows, sliced_actions
    )
    used_suspensions, calendar_version = _validate_rows_with_suspensions(
        normalized_rows,
        normalized_actions,
        verified_suspensions=verified_suspensions,
    )
    context = factor_context or {}
    valuation_rows = list(context.get("valuation_rows") or [])
    sentiment_rows = context.get("sentiment_rows")
    external_truth, external_coverage = build_external_factor_truth(
        normalized_rows,
        valuation_rows=valuation_rows,
        sentiment_rows=sentiment_rows,
    )
    item = {
        "code": code,
        "name": name,
        "role": "full_universe",
        "category": category_for_code(code),
        "independent_key": independent_key(code, sorted(indices)),
        "indices": sorted(indices),
        "rows": normalized_rows,
        "actions": normalized_actions,
        "source": source,
        "factor_context": {
            "valuation_index_codes": list(context.get("valuation_index_codes") or []),
            "valuation_rows": valuation_rows,
            "sentiment_category_keys": list(
                context.get("sentiment_category_keys") or []
            ),
            "sentiment_rows": sentiment_rows,
            "availability": external_coverage,
        },
        "factor_truth": factor_truth_rows(
            normalized_rows,
            turning,
            normalized_actions["dividends"],
            external_truth=external_truth,
        ),
    }
    coverage = {
        "rows": len(normalized_rows),
        "start": normalized_rows[0]["trade_date"],
        "end": normalized_rows[-1]["trade_date"],
        "calendar_version": calendar_version,
        "normalized_splits": conversion,
        "verified_suspensions": used_suspensions,
        "external": external_coverage,
    }
    return item, coverage
