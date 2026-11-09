"""统一回测入口：数据质量门槛、权益源核验与不可变回测核算，供策略与复盘共用。"""

import hashlib
import json
from datetime import UTC, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.backtest import ENGINE_VERSION, run_backtest
from app.backtest_data import (
    DATA_VERSION,
    fetch_actions,
    trading_days,
    validate_market,
)
from app.collection import now
from app.db import Session
from app.models import BacktestRun, BacktestSource, Candle, Instrument
from app.strategies import get_strategy, strategy_catalog, validate_parameters

router = APIRouter(prefix="/backtests", tags=["策略回测"])


class BacktestRequest(BaseModel):
    """回测研究假设，金额为人民币元，费率为小数，滑点为基点。"""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    instrument_code: str = Field(pattern=r"^\d{6}$")
    strategy_key: str = "ma_trend"
    parameters: dict[str, StrictInt] = Field(
        default_factory=lambda: {"window": 60}, strict=True
    )
    start_date: date
    end_date: date
    initial_cash: Decimal = Field(
        default=Decimal(50000), ge=1000, le=100000000, decimal_places=2
    )
    commission_rate: Decimal = Field(
        default=Decimal("0.0001"), ge=0, le=Decimal("0.01")
    )
    minimum_commission: Decimal = Field(
        default=Decimal(0), ge=0, le=100, decimal_places=2
    )
    slippage_bps: Decimal = Field(default=Decimal(5), ge=0, le=100)


def digest(snapshot):
    """对十进制字符串组成的规范输入计算摘要。"""
    return hashlib.sha256(
        json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def describe(run, *, detail=False):
    """返回实验概要；完整输入仅留存本地，前端按需读取结果。"""
    snapshot = run.input_snapshot
    result = {
        "id": run.backtest_run_id,
        "instrument_code": run.instrument_code,
        "strategy_key": run.strategy_key,
        "strategy_name": get_strategy(run.strategy_key)["metadata"]["name"],
        "created_at": run.created_at.astimezone(UTC),
        "input_sha256": run.input_sha256,
        "settings": snapshot["settings"],
        "engine_version": snapshot["engine_version"],
        "strategy_version": snapshot["strategy_version"],
        "actual_start": run.result_snapshot["strategy"]["daily"][0]["trade_date"],
        "actual_end": run.result_snapshot["strategy"]["daily"][-1]["trade_date"],
        "metrics": run.result_snapshot["strategy"]["metrics"],
    }
    if detail:
        result.update(
            result=run.result_snapshot,
            provenance={
                k: v for k, v in snapshot["source"].items() if k != "source_html"
            },
            calendar_version=snapshot["calendar_version"],
            warmup_count=sum(
                r["trade_date"] < result["actual_start"] for r in snapshot["rows"]
            ),
            data_cutoff=snapshot["rows"][-1]["trade_date"],
        )
    return result


@router.get("/catalog")
def catalog():
    """注册表与本地数据覆盖，不在页面加载时请求外部来源。"""
    with Session() as db:
        instruments = []
        for code in db.scalars(select(Instrument.code).order_by(Instrument.code)):
            instrument = db.get(Instrument, code)
            dates = list(
                db.scalars(
                    select(Candle.date).where(Candle.code == code).order_by(Candle.date)
                )
            )
            source = db.get(BacktestSource, code)
            instruments.append(
                {
                    "instrument_code": code,
                    "instrument_name": instrument.name if instrument else code,
                    "count": len(dates),
                    "first_date": dates[0] if dates else None,
                    "last_date": dates[-1] if dates else None,
                    "default_start": dates[60] if len(dates) > 60 else None,
                    "source_checked_through": source.checked_through_date
                    if source
                    else None,
                }
            )
    return {
        "strategies": strategy_catalog(),
        "instruments": instruments,
        "engine_version": ENGINE_VERSION,
    }


@router.post("/sources/refresh")
def refresh_sources(instrument_code: str | None = None):
    """核验配置内标的权益源后原子更新，失败保留原数据。"""
    with Session() as db:
        codes = list(db.scalars(select(Instrument.code).order_by(Instrument.code)))
    if instrument_code is not None:
        if instrument_code not in codes:
            raise HTTPException(404, "ETF不在配置范围内")
        codes = [instrument_code]
    try:
        sources = [(code, fetch_actions(code)) for code in codes]
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from None
    with Session() as db:
        for code, source in sources:
            values = {
                "instrument_code": code,
                "corporate_actions": source.pop("actions"),
                "checked_through_date": source["collected_at"].date(),
                **source,
            }
            statement = insert(BacktestSource).values(**values)
            db.execute(
                statement.on_conflict_do_update(
                    index_elements=["instrument_code"],
                    set_={k: v for k, v in values.items() if k != "instrument_code"},
                )
            )
        db.commit()
    return {"updated": codes}


def execute_backtest(body: BacktestRequest, db):
    """在调用方一致性事务内校验、计算并暂存不可变实验；由调用方提交。"""
    if body.start_date > body.end_date or body.end_date >= now().date():
        raise HTTPException(422, "起止日期无效，截止日须早于今天")
    try:
        validate_parameters(body.strategy_key, body.parameters)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # 防止采集修订恰好发生在行情与权益两次读取之间。
    if not db.get(Instrument, body.instrument_code):
        raise HTTPException(404, "ETF不在配置范围内")
    source = db.get(BacktestSource, body.instrument_code)
    if not source or source.checked_through_date < body.end_date:
        raise HTTPException(422, "权益来源缺失或读取时点早于截止日，请先更新分红资料")
    candles = db.scalars(
        select(Candle)
        .where(Candle.code == body.instrument_code, Candle.date <= body.end_date)
        .order_by(Candle.date)
    ).all()
    if not candles or body.start_date < candles[0].date:
        raise HTTPException(422, "起始日期早于本地行情覆盖，或暂无行情")
    rows = [
        {
            "trade_date": str(r.date),
            **{
                k: str(getattr(r, k)) if getattr(r, k) is not None else None
                for k in (
                    "open",
                    "high",
                    "low",
                    "close",
                    "adjusted_close",
                    "volume",
                )
            },
            "source_updated_at": r.source_updated_at,
            "collected_at": r.collected_at.isoformat(),
        }
        for r in candles
    ]
    settings = body.model_dump(mode="json")
    try:
        days, calendar_version = trading_days(
            rows[0]["trade_date"], settings["end_date"]
        )
        if not days or days[-1] != rows[-1]["trade_date"]:
            raise ValueError("截止日前的交易日行情缺失，请先补采或缩短区间")
        validate_market(rows, source.corporate_actions)
        result = run_backtest(rows, source.corporate_actions["dividends"], settings)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    snapshot = {
        "settings": settings,
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
        "engine_version": ENGINE_VERSION,
        "strategy_version": get_strategy(body.strategy_key)["metadata"]["version"],
        "data_version": DATA_VERSION,
    }
    run = BacktestRun(
        instrument_code=body.instrument_code,
        strategy_key=body.strategy_key,
        created_at=now(),
        input_sha256=digest(snapshot),
        input_snapshot=snapshot,
        result_snapshot=result,
    )
    db.add(run)
    db.flush()
    return describe(run, detail=True)
