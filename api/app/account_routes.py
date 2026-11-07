"""配置内 ETF 实盘持仓、委托与同步状态查询。"""

import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.account import DEFAULT_ACCOUNT_ID, format_source_time
from app.account_state import latest_holdings
from app.account_sync import AccountSyncBusy, sync_account
from app.collection import now
from app.db import Session
from app.models import (
    AccountEntrust,
    AccountSyncRun,
    Candle,
    Instrument,
)

router = APIRouter(prefix="/account", tags=["账户复盘"])


def _run_payload(run: AccountSyncRun) -> dict:
    """序列化同步批次，不包含账户资金号或源明细。"""
    return {
        "id": run.sync_run_id,
        "status": run.status,
        "range_start": run.range_start,
        "range_end": run.range_end,
        "fetched_count": run.fetched_count,
        "stored_count": run.stored_count,
        "skipped_count": run.skipped_count,
        "error_count": run.error_count,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
    }


@router.post("/sync")
def run_account_sync():
    """手动同步配置内持仓和成交；同步过程只读外部源并写本地库。"""
    try:
        return sync_account()
    except AccountSyncBusy as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/sync/status")
def sync_status():
    """返回最近一次同步及最近十次批次。"""
    with Session() as db:
        runs = db.scalars(
            select(AccountSyncRun)
            .where(AccountSyncRun.account_id == DEFAULT_ACCOUNT_ID)
            .order_by(AccountSyncRun.sync_run_id.desc())
            .limit(10)
        ).all()
        latest = _run_payload(runs[0]) if runs else None
        return {"latest": latest, "runs": [_run_payload(run) for run in runs]}


@router.get("/holdings")
def holdings():
    """返回配置内最新持仓快照和按本地收盘计算的市值。"""
    with Session() as db:
        latest, rows = latest_holdings(db, DEFAULT_ACCOUNT_ID)
        if latest is None:
            return {
                "as_of": None,
                "items": [],
                "summary": {
                    "holding_count": 0,
                    "market_value": None,
                    "cost_value": None,
                    "unrealized_pnl": None,
                    "configured_only": True,
                },
            }
        items = []
        market_total = 0.0
        cost_total = 0.0
        unrealized_total = 0.0
        for row in rows:
            instrument = db.get(Instrument, row.instrument_code)
            candle = db.scalar(
                select(Candle)
                .where(
                    Candle.code == row.instrument_code,
                    Candle.date <= latest,
                )
                .order_by(Candle.date.desc())
                .limit(1)
            )
            current = float(row.current_amount)
            close = float(candle.close) if candle else None
            cost_price = float(row.cost_price) if row.cost_price is not None else None
            market_value = current * close if close is not None else None
            cost_value = current * cost_price if cost_price is not None else None
            unrealized = (
                market_value - cost_value
                if market_value is not None and cost_value is not None
                else None
            )
            if market_value is not None:
                market_total += market_value
            if cost_value is not None:
                cost_total += cost_value
            if unrealized is not None:
                unrealized_total += unrealized
            items.append(
                {
                    "instrument_code": row.instrument_code,
                    "instrument_name": instrument.name if instrument else row.instrument_code,
                    "current_amount": current,
                    "enable_amount": float(row.enable_amount),
                    "frozen_amount": float(row.frozen_amount),
                    "uncome_buy_amount": float(row.uncome_buy_amount),
                    "uncome_sell_amount": float(row.uncome_sell_amount),
                    "cost_price": cost_price,
                    "latest_close": close,
                    "latest_close_date": candle.date if candle else None,
                    "market_value": market_value,
                    "cost_value": cost_value,
                    "unrealized_pnl": unrealized,
                    "weight": None,
                    "data_date": row.data_date,
                    "source_etl_time": row.source_etl_time,
                    "collected_at": row.collected_at,
                }
            )
        if market_total:
            for item in items:
                if item["market_value"] is not None:
                    item["weight"] = item["market_value"] / market_total
        return {
            "as_of": latest,
            "items": items,
            "summary": {
                "holding_count": len(items),
                "market_value": market_total,
                "cost_value": cost_total,
                "unrealized_pnl": unrealized_total,
                "configured_only": True,
            },
        }


@router.get("/entrusts")
def entrusts(
    start: date | None = None,
    end: date | None = None,
    instrument_code: str | None = None,
    limit: int = 200,
):
    """返回配置内委托/成交，默认最近30天，最多500行。"""
    end = end or now().date()
    start = start or (end - timedelta(days=30))
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    if instrument_code is not None and not re.fullmatch(r"\d{6}", instrument_code):
        raise HTTPException(422, "ETF代码无效")
    limit = max(1, min(limit, 500))
    with Session() as db:
        statement = select(AccountEntrust).where(
            AccountEntrust.account_id == DEFAULT_ACCOUNT_ID,
            AccountEntrust.curr_date >= start,
            AccountEntrust.curr_date <= end,
        )
        if instrument_code is not None:
            statement = statement.where(
                AccountEntrust.instrument_code == instrument_code
            )
        rows = db.scalars(
            statement.order_by(
                AccountEntrust.curr_date.desc(), AccountEntrust.entrust_no.desc()
            ).limit(limit)
        ).all()
        items = []
        for row in rows:
            instrument = db.get(Instrument, row.instrument_code)
            items.append(
                {
                    "instrument_code": row.instrument_code,
                    "instrument_name": instrument.name if instrument else row.instrument_code,
                    "curr_date": row.curr_date,
                    "curr_time": row.curr_time,
                    "display_time": format_source_time(row.curr_time),
                    "init_date": row.init_date,
                    "entrust_no": row.entrust_no,
                    "order_id": row.order_id,
                    "side": "buy"
                    if row.entrust_side == "1"
                    else "sell"
                    if row.entrust_side == "2"
                    else row.entrust_side,
                    "entrust_amount": float(row.entrust_amount),
                    "entrust_price": float(row.entrust_price),
                    "entrust_type": row.entrust_type,
                    "business_amount": float(row.business_amount),
                    "business_price": float(row.business_price),
                    "business_balance": float(row.business_balance),
                    "withdraw_amount": float(row.withdraw_amount),
                    "entrust_status": row.entrust_status,
                    "fare_kind": row.fare_kind,
                    "fee_amount": float(row.fee_amount),
                    "data_date": row.data_date,
                    "source_etl_time": row.source_etl_time,
                }
            )
        return {"start": start, "end": end, "count": len(items), "items": items}
