"""单ETF统一比较及盘前条件所需的本地数据快照，明确修订历史边界。"""

from sqlalchemy import select

from app.backtest_data import DATA_VERSION, trading_days, validate_market
from app.index_valuation import rolling_percentiles
from app.models import (
    BacktestSource,
    Candle,
    IndexValuationDaily,
    InstrumentIndexLink,
    NationalTeamDaily,
    SentimentDaily,
)
from app.strategy_conditions import external_key

VALUATIONS = {
    "pe_percentile": "pe",
    "pb_percentile": "pb",
    "dividend_yield": "xilv",
    "roe": "roe",
    "risk_premium": "premium_diff",
}


def market_snapshot(db, code, end, collected_before=None):
    """读取同事务行情与权益并校验完整日历，保留原始证据。

    Args:
        db: 调用方的一致性数据库会话。
        code: 可交易ETF六位证券代码。
        end: 最后纳入的源日期。
        collected_before: 盘前决策允许的最晚本地采集时间；历史研究为空。

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
    rows = [
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
    days, calendar_version = trading_days(rows[0]["trade_date"], str(end))
    if not days or days[-1] != rows[-1]["trade_date"]:
        raise ValueError("截止日前完整交易日行情缺失，请补采或明确调整区间")
    validate_market(rows, source.corporate_actions)
    return {
        "rows": rows,
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


def external_snapshot(db, code, rules, end, collected_before=None):
    """冻结映射明确的外部指标，不跨缺日填充，也不将采集日期当发布日期。

    Args:
        db: 一致性读取会话。
        code: ETF主体代码。
        rules: 本次比较或每日决策的全部规则。
        end: 输入源日期上界。
        collected_before: 前向决策的实际采集时间上界。

    Returns:
        指标键到源日期到数值与采集证据的映射；无资料保留空映射。
    """
    items = {
        external_key(item): item
        for rule in rules
        for side in ("buy", "sell")
        for item in rule[side]["conditions"]
        if item["indicator"] not in ("trend", "momentum", "volatility")
    }
    result = {}
    links = list(
        db.scalars(
            select(InstrumentIndexLink.index_code).where(
                InstrumentIndexLink.instrument_code == code
            )
        )
    )
    for key, item in items.items():
        indicator = item["indicator"]
        if indicator in VALUATIONS:
            if len(links) != 1:
                result[key] = {}
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
                query = query.where(
                    IndexValuationDaily.collected_at <= collected_before
                )
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
            result[key] = {
                str(row.trade_date): {
                    "value": str(value) if value is not None else None,
                    "source_date": str(row.trade_date),
                    "collected_at": row.collected_at.isoformat(),
                    "index_code": row.index_code,
                    "evidence_type": "revised",
                }
                for row, value in zip(records, values, strict=True)
            }
        else:
            model = SentimentDaily if indicator == "sentiment" else NationalTeamDaily
            query = (
                select(model).where(model.trade_date <= end).order_by(model.trade_date)
            )
            query = (
                query.where(model.category_key == item["category_key"])
                if indicator == "sentiment"
                else query.where(model.instrument_code == code)
            )
            if collected_before:
                query = query.where(model.collected_at <= collected_before)
            records = list(db.scalars(query))
            field = (
                "fear_greed_score"
                if indicator == "sentiment"
                else "estimated_holding_pct"
            )
            result[key] = {
                str(row.trade_date): {
                    "value": str(getattr(row, field))
                    if getattr(row, field) is not None
                    else None,
                    "source_date": str(row.trade_date),
                    "collected_at": row.collected_at.isoformat(),
                    "evidence_type": "revised",
                }
                for row in records
            }
    return result


def condition_coverage(db, code):
    """根据本地覆盖和映射给出三态资格，不承诺所有交易日都齐备。"""
    from app.models import NationalTeamInstrument, SentimentCategory
    from app.strategy_conditions import CONDITIONS

    dates = list(
        db.scalars(select(Candle.date).where(Candle.code == code).order_by(Candle.date))
    )
    source = db.get(BacktestSource, code)
    links = list(
        db.scalars(
            select(InstrumentIndexLink.index_code).where(
                InstrumentIndexLink.instrument_code == code
            )
        )
    )
    result = []
    for item in CONDITIONS:
        key = item["key"]
        available_dates = dates
        reason = "行情与权益逐日校验后可回测；窗口预热另行核验"
        if key in VALUATIONS:
            available_dates = list(
                db.scalars(
                    select(IndexValuationDaily.trade_date)
                    .where(
                        IndexValuationDaily.index_code.in_(links)
                        if len(links) == 1
                        else False,
                        IndexValuationDaily.metric_key == VALUATIONS[key],
                        IndexValuationDaily.value_status == "valid",
                    )
                    .order_by(IndexValuationDaily.trade_date)
                )
            )
            reason = "按当前可获取历史计算，未证明原时点可得；仅使用明确关联指数"
        elif key == "national_team_change":
            available_dates = (
                list(
                    db.scalars(
                        select(NationalTeamDaily.trade_date)
                        .where(
                            NationalTeamDaily.instrument_code == code,
                            NationalTeamDaily.estimated_holding_pct.is_not(None),
                        )
                        .order_by(NationalTeamDaily.trade_date)
                    )
                )
                if db.get(NationalTeamInstrument, code)
                else []
            )
            reason = "固定2026-01-01基准的估算比例，可能修订，变化单位为百分点"
        elif key == "sentiment":
            available_dates = (
                list(
                    db.scalars(
                        select(SentimentDaily.trade_date).order_by(
                            SentimentDaily.trade_date
                        )
                    )
                )
                if db.scalar(select(SentimentCategory.category_key).limit(1))
                else []
            )
            reason = "必须明确选择市场背景类别；覆盖需按所选类别与每个决策日再核验"
        status = (
            item["evidence_type"]
            if available_dates and (source or item["evidence_type"] == "revised")
            else "unavailable"
        )
        if status == "unavailable":
            reason = (
                "缺少本地覆盖、权益资料或明确映射，请先在数据管理补齐；不以零值代替"
            )
        result.append(
            {
                "key": key,
                "status": status,
                "reason": reason,
                "first_date": str(available_dates[0]) if available_dates else None,
                "last_date": str(available_dates[-1]) if available_dates else None,
            }
        )
    return {
        "instrument_code": code,
        "conditions": result,
        "warmup_note": "统一比较逐项检查预热与完整共同日历，所列范围不保证区间无缺口",
    }
