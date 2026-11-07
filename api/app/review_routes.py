"""配置内 ETF 实际复盘与统一资金研究，分别返回数据资格。"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.account import DEFAULT_SYNC_START
from app.account_review import calculate_actual, coverage_gaps
from app.account_state import latest_holdings
from app.backtest_data import trading_days, validate_market
from app.backtest_routes import BacktestRequest, digest, execute_backtest
from app.collection import now
from app.db import Session
from app.models import (
    AccountEntrust,
    AccountSyncRun,
    BacktestSource,
    Candle,
    Instrument,
)

router = APIRouter(prefix="/account", tags=["投资复盘"])


@router.get("/review/{instrument_code}")
def review(
    instrument_code: str,
    start: date,
    end: date,
    confirm_zero_opening: bool = False,
    confirm_trade_dates: bool = False,
):
    """读取全量累计成交，准入后核算；人工确认只作用于本次研究，不改源数据。

    两项确认分别证明同步起点无旧仓、累计成交属于委托日；不能由数量相符替代。
    未确认仍返回标记与质量证据，但不输出未经核验的盈亏。
    """
    if start > end or end >= now().date() or start < DEFAULT_SYNC_START:
        raise HTTPException(422, "复盘须从账户同步起点之后开始，截止早于今天")
    try:
        days, calendar_version = trading_days(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not days:
        raise HTTPException(422, "所选区间没有交易日")
    finish = date.fromisoformat(days[-1])
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if not db.get(Instrument, instrument_code):
            raise HTTPException(404, "ETF不在配置范围内")
        runs = list(
            db.scalars(
                select(AccountSyncRun)
                .where(AccountSyncRun.account_id == 1)
                .order_by(AccountSyncRun.sync_run_id)
            )
        )
        good = [
            (r.range_start, r.range_end)
            for r in runs
            if r.status == "success" and r.range_start and r.range_end
        ]
        gaps = coverage_gaps(good, DEFAULT_SYNC_START, finish)
        issues = []
        if gaps:
            issues.append(
                "完整同步覆盖不足：" + "、".join(f"{a}至{b}" for a, b in gaps)
            )
        # 晚于完整覆盖的失败批次需要成功重取其整段，不能用高水位掩盖异常。
        for run in runs:
            if run.status != "success" and run.range_start and run.range_end:
                left, right = run.range_start, min(finish, run.range_end)
                repairs = [
                    (r.range_start, r.range_end)
                    for r in runs
                    if r.sync_run_id > run.sync_run_id
                    and r.status == "success"
                    and r.range_start
                    and r.range_end
                ]
                if left <= right and coverage_gaps(repairs, left, right):
                    issues.append(
                        f"同步批次{run.sync_run_id}的错误或运行状态尚未完整修复"
                    )
        source = db.get(BacktestSource, instrument_code)
        if not source or source.checked_through_date < finish:
            issues.append("权益来源缺失或核验日期早于区间末日，请更新权益资料")
        actions = (
            source.corporate_actions if source else {"dividends": [], "splits": []}
        )
        if any(
            str(DEFAULT_SYNC_START) <= e["effective_date"] <= str(finish)
            for e in actions["splits"]
        ):
            issues.append("历史包含份额折算，当前核算不支持该折算，请勿据此计算收益")
        entries = list(
            db.scalars(
                select(AccountEntrust)
                .where(
                    AccountEntrust.account_id == 1,
                    AccountEntrust.instrument_code == instrument_code,
                )
                .order_by(AccountEntrust.curr_date, AccountEntrust.entrust_no)
            )
        )
        fields = [
            "curr_date",
            "entrust_side",
            "business_amount",
            "business_balance",
            "clear_balance",
            "entrust_no",
        ]
        trades = [
            {k: getattr(t, k) for k in fields} for t in entries if t.business_amount > 0
        ]
        if any(
            t.init_date is not None and t.init_date != t.curr_date
            for t in entries
            if t.business_amount > 0
        ):
            issues.append("存在跨日委托，成交所属交易日待核验")
        if not confirm_zero_opening:
            issues.append("尚未确认2025-01-20同步起点前该ETF持仓为零")
        if not confirm_trade_dates:
            issues.append("尚未确认累计成交属于委托日期；委托时间不等于成交时间")
        candles = list(
            db.scalars(
                select(Candle)
                .where(
                    Candle.code == instrument_code,
                    Candle.date >= DEFAULT_SYNC_START - timedelta(days=15),
                    Candle.date <= finish,
                )
                .order_by(Candle.date)
            )
        )
        prices = [(c.date, c.close) for c in candles]
        if source and candles:
            market_rows = [
                {
                    "trade_date": str(c.date),
                    **{
                        key: str(getattr(c, key))
                        if getattr(c, key) is not None
                        else None
                        for key in (
                            "open",
                            "high",
                            "low",
                            "close",
                            "adjusted_close",
                            "volume",
                        )
                    },
                }
                for c in candles
                if c.date >= DEFAULT_SYNC_START
            ]
            try:
                validate_market(market_rows, actions)
            except ValueError as exc:
                issues.append(str(exc))

        expected, _ = trading_days(
            max(DEFAULT_SYNC_START, candles[0].date) if candles else DEFAULT_SYNC_START,
            finish,
        )
        if any(d not in {str(c.date) for c in candles} for d in expected):
            issues.append("本地覆盖起点至截止日的交易日行情存在缺口")
        if any(c.close is None or c.close <= 0 for c in candles):
            issues.append("存在无效收盘价")
        snapshot_date, holding_rows = latest_holdings(db)
        snapshot = next((row for row in holding_rows if row.instrument_code == instrument_code), None)
        quantity_delta = None
        if snapshot_date is None or snapshot_date < finish:
            issues.append("持仓快照缺失或早于复盘截止日，不能对账")
        else:
            if coverage_gaps(good, DEFAULT_SYNC_START, snapshot_date):
                issues.append("同步覆盖未延伸到持仓快照日期，不能对账")
            net = sum(
                (
                    t["business_amount"] * (1 if t["entrust_side"] == "1" else -1)
                    for t in trades
                    if t["curr_date"] <= snapshot_date
                ),
                Decimal(0),
            )
            quantity_delta = net - (snapshot.current_amount if snapshot else Decimal(0))
            if quantity_delta:
                issues.append("历史成交净量与持仓快照不一致")
            if snapshot and (
                snapshot.uncome_buy_amount
                or snapshot.uncome_sell_amount
                or snapshot.frozen_amount
            ):
                issues.append("快照存在在途或冻结数量，待确认结算")
        provenance = {
            "version": "actual-etf-1.0",
            "start": str(start),
            "end": str(finish),
            "trades": [{k: str(v) for k, v in t.items()} for t in trades],
            "prices": [(str(d), str(v)) for d, v in prices],
            "actions": actions,
            "source_sha256": source.source_sha256 if source else None,
            "confirmations": {
                "zero_opening": confirm_zero_opening,
                "trade_dates": confirm_trade_dates,
            },
        }
        actual = {"status": "blocked", "reasons": list(dict.fromkeys(issues))}
        if not any(t["curr_date"] <= finish for t in trades):
            actual = {
                "status": "not_applicable",
                "reasons": ["没有实际成交历史；可单独开展规则研究"],
            }
        elif not issues:
            try:
                actual = calculate_actual(
                    trades, prices, actions["dividends"], start, finish
                )
            except ValueError as exc:
                actual = {"status": "blocked", "reasons": [str(exc)]}
        actual["input_sha256"] = digest(provenance)
        actual["version"] = provenance["version"]
        markers = [
            {
                "trade_date": str(t["curr_date"]),
                "side": "buy" if t["entrust_side"] == "1" else "sell",
                "quantity": str(t["business_amount"]),
                "price": str(t["business_balance"] / t["business_amount"]),
            }
            for t in trades
            if start <= t["curr_date"] <= finish and t["entrust_side"] in ("1", "2")
        ]
        return {
            "actual": actual,
            "markers": markers,
            "start": start,
            "end": finish,
            "quality": {
                "issues": list(dict.fromkeys(issues)),
                "snapshot_date": snapshot_date,
                "market_date": candles[-1].date if candles else None,
                "source_checked_through": source.checked_through_date
                if source
                else None,
                "quantity_delta": str(quantity_delta)
                if quantity_delta is not None
                else None,
                "calendar_version": calendar_version,
            },
            "comparability": "真实项目现金流与固定资金研究分开展示，不计算二者超额；本次确认不修改源数据",
        }


@router.post("/research/{instrument_code}")
def research(
    instrument_code: str,
    start: date,
    end: date,
    initial_cash: Annotated[
        Decimal, Query(ge=1000, le=100000000, decimal_places=2)
    ] = Decimal(50000),
    commission_rate: Annotated[Decimal, Query(ge=0, le=Decimal(".01"))] = Decimal(
        "0.0001"
    ),
    minimum_commission: Annotated[
        Decimal, Query(ge=0, le=100, decimal_places=2)
    ] = Decimal(0),
    slippage_bps: Annotated[Decimal, Query(ge=0, le=100)] = Decimal(5),
):
    """复用统一引擎与不可变实验，全部基线须同起止、成本与权益口径。"""
    if (
        len(instrument_code) != 6
        or not instrument_code.isascii()
        or not instrument_code.isdigit()
    ):
        raise HTTPException(422, "ETF代码须为六位数字")
    settings = {
        "instrument_code": instrument_code,
        "start_date": start,
        "end_date": end,
        "initial_cash": initial_cash,
        "commission_rate": commission_rate,
        "minimum_commission": minimum_commission,
        "slippage_bps": slippage_bps,
    }
    # 先核验最长预热；失败时不生成起点不同的短均线实验。
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        long = execute_backtest(
            BacktestRequest(**settings, parameters={"window": 60}), db
        )
        short = execute_backtest(
            BacktestRequest(**settings, parameters={"window": 20}), db
        )
        db.commit()
    tracks = [
        dict(name="买入持有", **long["result"]["benchmark"]),
        dict(name="20日均线", **short["result"]["strategy"]),
        dict(name="60日均线", **long["result"]["strategy"]),
    ]
    for track in tracks:
        track["metrics"]["time_in_market"] = sum(
            r["quantity"] > 0 for r in track["daily"]
        ) / len(track["daily"])
    tracks.append(
        {
            "name": "现金（零利息）",
            "daily": [
                {"trade_date": r["trade_date"], "nav": 1, "drawdown": 0, "quantity": 0}
                for r in tracks[0]["daily"]
            ],
            "metrics": {
                "total_return": 0,
                "max_drawdown": 0,
                "commission": "0",
                "turnover": 0,
                "time_in_market": 0,
            },
        }
    )
    return {
        "tracks": tracks,
        "settings": long["settings"],
        "experiment_ids": [long["id"], short["id"]],
        "input_sha256": [long["input_sha256"], short["input_sha256"]],
        "note": "固定名义研究资金；按当前配置事后选取研究范围，不代表真实分配资金或事前选基能力",
    }
