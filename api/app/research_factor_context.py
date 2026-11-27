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
MARKET_REGIME_FACTORS = (
    "market_ivix_high",
    "market_ivix_calm",
    "market_breadth_weak",
    "market_futures_deep_discount",
)
MARKET_REGIME_KEYS = ("volatility", "premium", "strength")
MARKET_IVIX_HIGH = Decimal(22)
MARKET_IVIX_CALM = Decimal(16)
MARKET_IVIX_FAST_EXPANSION_RATIO = Decimal("1.1")
MARKET_BREADTH_WEAK = Decimal(1)
MARKET_FUTURES_DEEP_DISCOUNT = Decimal(-10)
MARKET_EXTREME_FEAR = Decimal(25)
MARKET_EXTREME_GREED = Decimal(75)


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


def _market_regime_changes(market_rows, market_regime_rows):
    """将原始全市场观测转换为仅由当日及更早数据决定的状态变更。"""
    market_scores = {}
    for row in market_rows:
        day = _date(row["trade_date"])
        score = _decimal(row["fear_greed_score"])
        if not Decimal(0) <= score <= Decimal(100):
            raise ValueError("全市场恐贪分数超出有效范围")
        if day in market_scores and market_scores[day] != score:
            raise ValueError("全市场恐贪日期重复")
        market_scores[day] = score

    by_key = {key: [] for key in MARKET_REGIME_KEYS}
    for row in market_regime_rows:
        key = row["factor_key"]
        if key in by_key:
            by_key[key].append((_date(row["trade_date"]), _decimal(row["raw_value"])))

    changes = {}
    regime_days = set()
    for key, series in by_key.items():
        ordered = sorted(series)
        if len({day for day, _ in ordered}) != len(ordered):
            raise ValueError("全市场环境子因子日期重复")
        values, previous = [], None
        for day, value in ordered:
            values.append(value)
            regime_days.add(day)
            item = changes.setdefault(day, {})
            if key == "volatility":
                percentile = (
                    Decimal(100)
                    * sum(prior < value for prior in values[-252:])
                    / len(values[-252:])
                )
                item["market_ivix_high"] = value >= MARKET_IVIX_HIGH or (
                    len(values) >= 120 and percentile >= Decimal(80)
                )
                item["market_ivix_calm"] = value <= MARKET_IVIX_CALM and (
                    previous is None
                    or value <= previous * MARKET_IVIX_FAST_EXPANSION_RATIO
                )
                previous = value
            elif key == "strength":
                item["market_breadth_weak"] = value <= MARKET_BREADTH_WEAK
            elif key == "premium":
                item["market_futures_deep_discount"] = (
                    value <= MARKET_FUTURES_DEEP_DISCOUNT
                )
    return market_scores, changes, regime_days


def build_external_factor_truth(
    rows,
    *,
    valuation_rows=(),
    sentiment_rows=None,
    market_rows=(),
    market_regime_rows=(),
):
    """生成严格早于 ETF 当日的外部因子真值及可得性摘要。"""
    valuation_changes, valuation_metrics = _valuation_changes(valuation_rows)
    sentiment_changes = (
        _sentiment_changes(sentiment_rows) if sentiment_rows is not None else {}
    )
    market_changes, regime_changes, regime_days = _market_regime_changes(
        market_rows, market_regime_rows
    )
    valuation_days = sorted(valuation_changes)
    sentiment_days = sorted(sentiment_changes)
    market_days = sorted(market_changes)
    regime_change_days = sorted(regime_changes)
    valuation_cursor = sentiment_cursor = market_cursor = regime_cursor = 0
    latest_percentiles, latest_sentiment, latest_market = {}, None, None
    latest_regime = {factor_id: False for factor_id in MARKET_REGIME_FACTORS}
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
        while market_cursor < len(market_days) and market_days[market_cursor] < day:
            latest_market = market_changes[market_days[market_cursor]]
            market_cursor += 1
        while (
            regime_cursor < len(regime_change_days)
            and regime_change_days[regime_cursor] < day
        ):
            latest_regime.update(regime_changes[regime_change_days[regime_cursor]])
            regime_cursor += 1

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
        if latest_market is not None:
            item["market_fear_extreme"] = latest_market <= MARKET_EXTREME_FEAR
            item["market_greed_extreme"] = latest_market >= MARKET_EXTREME_GREED
        item.update(latest_regime)
        truth.append(item)

    valuation_available = bool(valuation_changes)
    sentiment_available = bool(sentiment_changes)
    market_source_days = set(market_days) | regime_days
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
        "market_regime": {
            "available": bool(market_source_days),
            "first_source_date": str(min(market_source_days))
            if market_source_days
            else None,
            "last_source_date": str(max(market_source_days))
            if market_source_days
            else None,
            "factors": {
                key: {
                    "available": bool(series),
                    "first_source_date": str(min(day for day, _ in series))
                    if series
                    else None,
                    "last_source_date": str(max(day for day, _ in series))
                    if series
                    else None,
                }
                for key, series in {
                    key: [
                        (_date(row["trade_date"]), _decimal(row["raw_value"]))
                        for row in market_regime_rows
                        if row["factor_key"] == key
                    ]
                    for key in ("volatility", "bx", "premium", "wz", "strength")
                }.items()
            },
            "as_of_policy": "ETF当日只使用严格早于该日的全市场恐贪与五维源观测；源全历史分位不参与策略真值。",
        },
    }
    return truth, coverage
