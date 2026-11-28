"""单ETF算法模板比较及盘前信号所需的数据快照，明确修订历史边界。"""

from sqlalchemy import select

from app.backtest_data import (
    DATA_VERSION,
    post_split_rows,
    trading_days,
    validate_market,
)
from app.index_valuation import rolling_percentiles
from app.models import (
    BacktestSource,
    Candle,
    IndexValuationDaily,
    InstrumentIndexLink,
    InstrumentVerifiedSuspension,
    MarketFearGreedDaily,
)
from app.shared_etf_snapshot import normalize_split_history

VALUATIONS = {
    "pe_percentile": "pe",
    "pb_percentile": "pb",
    "dividend_yield": "xilv",
    "roe": "roe",
    "risk_premium": "premium_diff",
}


def market_snapshot(
    db,
    code,
    end,
    collected_before=None,
    interval_start=None,
    allow_verified_suspensions=False,
    include_warmup_rows=False,
):
    """读取同事务行情与权益并校验完整日历，保留原始证据。

    Args:
        db: 调用方的一致性数据库会话。
        code: 可交易ETF六位证券代码。
        end: 最后纳入的源日期。
        collected_before: 盘前决策允许的最晚本地采集时间；历史研究为空。
        interval_start: 研究或信号区间起点；起点前的折算行情会被排除并重新预热。
        allow_verified_suspensions: 是否放行经跨源核验的真实停牌交易日。
        include_warmup_rows: 当起点前存在折算时，是否附带标准化全历史用于因子长周期预热。

    Returns:
        可独立复算的行情、权益、来源与日历快照。

    Raises:
        ValueError: 权益未核验、行情缺失或日期不完整。
    """
    source = db.get(BacktestSource, code)
    if (
        not source
        or source.checked_through_date < end
        or (collected_before and source.collected_at > collected_before)
    ):
        raise ValueError(
            "权益资料缺失、未核验到截止日或采集晚于决策时点，请更新权益资料"
        )
    statement = (
        select(Candle)
        .where(Candle.code == code, Candle.date <= end)
        .order_by(Candle.date)
    )
    if collected_before:
        statement = statement.where(Candle.collected_at <= collected_before)
    candles = list(db.scalars(statement))
    if not candles:
        raise ValueError("本地ETF行情缺失，请先采集")
    all_rows = [
        {
            "trade_date": str(row.date),
            **{
                key: str(getattr(row, key)) if getattr(row, key) is not None else None
                for key in ("open", "high", "low", "close", "adjusted_close", "volume")
            },
            "source_updated_at": row.source_updated_at,
            "collected_at": row.collected_at.isoformat(),
        }
        for row in candles
    ]
    rows = (
        post_split_rows(all_rows, source.corporate_actions["splits"], interval_start)
        if interval_start is not None
        else all_rows
    )
    days, calendar_version = trading_days(rows[0]["trade_date"], str(end))
    if not days or days[-1] != rows[-1]["trade_date"]:
        raise ValueError("截止日前完整交易日行情缺失，请补采或明确调整区间")
    verified_suspensions = ()
    if allow_verified_suspensions:
        verified_suspensions = sorted(
            str(item.trade_date)
            for item in db.scalars(
                select(InstrumentVerifiedSuspension).where(
                    InstrumentVerifiedSuspension.instrument_code == code,
                    InstrumentVerifiedSuspension.trade_date <= end,
                )
            )
            if isinstance(item.sources, list) and len(item.sources) >= 2
        )
    validate_market(
        rows,
        source.corporate_actions,
        verified_suspensions=verified_suspensions,
    )
    warmup_payload = {}
    if include_warmup_rows and len(all_rows) > len(rows):
        validate_market(
            all_rows,
            source.corporate_actions,
            allow_splits=True,
            verified_suspensions=verified_suspensions,
            ignore_pre_calendar_boundary=True,
        )
        warmup_rows, warmup_actions, _ = normalize_split_history(
            all_rows, source.corporate_actions
        )
        warmup_payload = {
            "warmup_rows": warmup_rows,
            "warmup_dividends": warmup_actions["dividends"],
        }
    return {
        "rows": rows,
        **warmup_payload,
        "actions": source.corporate_actions,
        "source": {
            "source_url": source.source_url,
            "source_sha256": source.source_sha256,
            "source_html": source.source_html,
            "checked_through_date": str(source.checked_through_date),
            "collected_at": source.collected_at.isoformat(),
            "market_source": "财通证券历史日行情",
        },
        "calendar_days": days,
        "calendar_version": calendar_version,
        "data_version": DATA_VERSION,
    }


def external_snapshot(db, code, metrics, end, collected_before=None):
    """冻结模板明确引用的指数估值，不跨缺日填充或将采集日期当发布日期。

    Args:
        db: 一致性读取会话。
        code: ETF主体代码。
        metrics: 服务端模板引用的估值指标键。
        end: 输入源日期上界。
        collected_before: 前向决策的实际采集时间上界。

    Returns:
        指标键到源日期的数值与采集证据映射；无资料保留空映射。
    """
    indicators = sorted(set(metrics))
    unknown = set(indicators) - VALUATIONS.keys()
    if unknown:
        raise ValueError("算法模板引用了不支持的估值指标")
    if not indicators:
        return {}
    links = list(
        db.scalars(
            select(InstrumentIndexLink.index_code).where(
                InstrumentIndexLink.instrument_code == code
            )
        )
    )
    result = {}
    for indicator in indicators:
        if len(links) != 1:
            result[indicator] = {}
            continue
        query = (
            select(IndexValuationDaily)
            .where(
                IndexValuationDaily.index_code == links[0],
                IndexValuationDaily.metric_key == VALUATIONS[indicator],
                IndexValuationDaily.trade_date <= end,
            )
            .order_by(IndexValuationDaily.trade_date)
        )
        if collected_before:
            query = query.where(IndexValuationDaily.collected_at <= collected_before)
        records = list(db.scalars(query))
        values = (
            rolling_percentiles(
                [
                    (row.trade_date, row.metric_value, row.value_status)
                    for row in records
                ]
            )
            if indicator in ("pe_percentile", "pb_percentile")
            else [
                row.metric_value if row.value_status == "valid" else None
                for row in records
            ]
        )
        result[indicator] = {
            str(row.trade_date): {
                "value": str(value) if value is not None else None,
                "source_date": str(row.trade_date),
                "collected_at": row.collected_at.isoformat(),
                "index_code": row.index_code,
                "evidence_type": "revised",
            }
            for row, value in zip(records, values, strict=True)
        }
    return result


def factor_external_snapshot(db, code, end, requirements, collected_before=None):
    """为基于因子表达式的比较与采用策略读取严格截至期末及采集时刻的外部上下文。"""
    payload = {}
    if "valuation" in requirements:
        links = list(
            db.scalars(
                select(InstrumentIndexLink.index_code).where(
                    InstrumentIndexLink.instrument_code == code
                )
            )
        )
        valuation_rows = []
        if len(links) == 1:
            query = (
                select(IndexValuationDaily)
                .where(
                    IndexValuationDaily.index_code == links[0],
                    IndexValuationDaily.trade_date <= end,
                )
                .order_by(
                    IndexValuationDaily.trade_date, IndexValuationDaily.metric_key
                )
            )
            if collected_before:
                query = query.where(
                    IndexValuationDaily.collected_at <= collected_before
                )
            valuation_rows = [
                {
                    "trade_date": str(row.trade_date),
                    "metric_key": row.metric_key,
                    "metric_value": str(row.metric_value),
                    "value_status": row.value_status,
                }
                for row in db.scalars(query)
            ]
        payload["valuation_rows"] = valuation_rows
    if "market_fear_greed" in requirements:
        query = (
            select(MarketFearGreedDaily)
            .where(MarketFearGreedDaily.trade_date <= end)
            .order_by(MarketFearGreedDaily.trade_date)
        )
        if collected_before:
            query = query.where(
                MarketFearGreedDaily.collected_at <= collected_before
            )
        payload["market_rows"] = [
            {
                "trade_date": str(row.trade_date),
                "fear_greed_score": str(row.fear_greed_score),
            }
            for row in db.scalars(query)
        ]
    return payload
