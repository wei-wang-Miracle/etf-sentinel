"""将外部估值和情绪观测因果对齐到 ETF 日行情。"""

from datetime import date
from decimal import Decimal, InvalidOperation

from app.index_valuation import rolling_percentiles
from app.research_factors import EXTERNAL_FACTOR_IDS

LOW_PERCENTILE = Decimal(30)
HIGH_PERCENTILE = Decimal(80)
EXTREME_FEAR = Decimal(20)
EXTREME_GREED = Decimal(80)
ERP_HIGH_PERCENTILE = Decimal(70)
ERP_LOW_PERCENTILE = Decimal(20)
DIVIDEND_YIELD_HIGH_PERCENTILE = Decimal(70)
VALUATION_METRICS = ("pe", "pb", "xilv", "roe", "premium_diff")


def _date(value):
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _decimal(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("外部因子数值非法") from exc
    if not parsed.is_finite():
        raise ValueError("外部因子数值非法")
    return parsed


def _empty_truth(day):
    return {"trade_date": day, **{factor_id: False for factor_id in EXTERNAL_FACTOR_IDS}}


def _valuation_changes(valuation_rows):
    """按源日期返回五类有效估值的因果本地历史分位变更。"""
    by_metric = {metric: [] for metric in VALUATION_METRICS}
    for row in valuation_rows:
        metric = row["metric_key"]
        if metric not in by_metric or row.get("value_status") != "valid":
            continue
        by_metric[metric].append(
            (_date(row["trade_date"]), _decimal(row["metric_value"]), "valid")
        )

    changes = {}
    for metric, series in by_metric.items():
        ordered = sorted(series)
        for (day, _, _), percentile in zip(
            ordered, rolling_percentiles(ordered), strict=True
        ):
            if percentile is not None:
                changes.setdefault(day, {})[metric] = Decimal(str(percentile))
    return changes, by_metric


def _sentiment_changes(sentiment_rows):
    """按源日期返回恐贪状态及首次恐惧回升事件。"""
    ordered = sorted(
        (_date(row["trade_date"]), _decimal(row["fear_greed_score"]))
        for row in sentiment_rows
    )
    if len({day for day, _ in ordered}) != len(ordered):
        raise ValueError("情绪观测日期重复")
    changes, previous_score = {}, None
    for day, score in ordered:
        changes[day] = {
            "fear": score <= EXTREME_FEAR,
            "greed": score >= EXTREME_GREED,
            "rebound": previous_score is not None
            and previous_score <= EXTREME_FEAR
            and score > previous_score,
        }
        previous_score = score
    return changes


def build_external_factor_truth(rows, *, valuation_rows=(), sentiment_rows=None):
    """生成严格早于 ETF 当日的外部因子真值及可得性摘要。"""
    valuation_changes, valuation_metrics = _valuation_changes(valuation_rows)
    sentiment_changes = (
        _sentiment_changes(sentiment_rows) if sentiment_rows is not None else {}
    )
    valuation_days = sorted(valuation_changes)
    sentiment_days = sorted(sentiment_changes)
    valuation_cursor = sentiment_cursor = 0
    latest_percentiles, latest_sentiment = {}, None
    pending_rebound = False
    truth = []

    for row in rows:
        day = _date(row["trade_date"])
        while valuation_cursor < len(valuation_days) and valuation_days[valuation_cursor] < day:
            source_day = valuation_days[valuation_cursor]
            latest_percentiles.update(valuation_changes[source_day])
            valuation_cursor += 1
        while sentiment_cursor < len(sentiment_days) and sentiment_days[sentiment_cursor] < day:
            source_day = sentiment_days[sentiment_cursor]
            latest_sentiment = sentiment_changes[source_day]
            pending_rebound = pending_rebound or latest_sentiment["rebound"]
            sentiment_cursor += 1

        item = _empty_truth(row["trade_date"])
        if latest_percentiles:
            item["valuation_low_percentile"] = any(
                latest_percentiles.get(metric, Decimal(101)) <= LOW_PERCENTILE
                for metric in ("pe", "pb")
            )
            item["valuation_high_percentile"] = any(
                latest_percentiles.get(metric, Decimal(-1)) >= HIGH_PERCENTILE
                for metric in ("pe", "pb")
            )
            erp_percentile = latest_percentiles.get("premium_diff")
            item["erp_high_percentile"] = (
                erp_percentile is not None and erp_percentile >= ERP_HIGH_PERCENTILE
            )
            item["erp_low_percentile"] = (
                erp_percentile is not None and erp_percentile <= ERP_LOW_PERCENTILE
            )
            dividend_percentile = latest_percentiles.get("xilv")
            item["dividend_yield_high"] = (
                dividend_percentile is not None
                and dividend_percentile >= DIVIDEND_YIELD_HIGH_PERCENTILE
            )
        if latest_sentiment is not None:
            item["sentiment_extreme_fear"] = latest_sentiment["fear"]
            item["sentiment_extreme_greed"] = latest_sentiment["greed"]
            item["sentiment_fear_rebound"] = pending_rebound
            pending_rebound = False
        truth.append(item)

    valuation_available = bool(valuation_changes)
    sentiment_available = bool(sentiment_changes)
    coverage = {
        "valuation": {
            "available": valuation_available,
            "first_source_date": str(valuation_days[0]) if valuation_days else None,
            "last_source_date": str(valuation_days[-1]) if valuation_days else None,
            "metrics": {
                metric: {
                    "available": bool(series),
                    "first_source_date": str(min(day for day, _, _ in series))
                    if series
                    else None,
                    "last_source_date": str(max(day for day, _, _ in series))
                    if series
                    else None,
                }
                for metric, series in valuation_metrics.items()
            },
            "as_of_policy": "ETF当日只使用严格早于该日的最近有效PE、PB、股息率、ROE或股债风险溢价源观测；源历史可能修订，不代表原时点发布快照。",
        },
        "sentiment": (
            {
                "available": sentiment_available,
                "first_source_date": str(sentiment_days[0]) if sentiment_days else None,
                "last_source_date": str(sentiment_days[-1]) if sentiment_days else None,
                "as_of_policy": "ETF当日只使用严格早于该日的最近恐贪源观测。",
            }
            if sentiment_rows is not None
            else {"available": False, "reason": "未建立ETF–恐贪类别映射"}
        ),
    }
    return truth, coverage
