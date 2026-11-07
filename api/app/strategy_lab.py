"""当前持仓ETF从候选研究到观察计划、真实执行核对的闭环接口。"""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from math import sqrt
from statistics import pstdev
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.account_state import latest_holdings
from app.backtest import ENGINE_VERSION, metrics
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
    StrategyExecutionLink,
    StrategyObservation,
    StrategyResearchBatch,
    StrategySignal,
)
from app.strategies import features, get_strategy
from app.strategy_research import (
    CANDIDATES,
    RESEARCH_CASH,
    RESEARCH_VERSION,
    diagnostics,
    pareto_keys,
    with_reserve,
)

router = APIRouter(prefix="/strategy-lab", tags=["持仓策略闭环"])
COSTS = {"commission_rate": "0.0001", "minimum_commission": "0", "slippage_bps": "5"}
TZ = ZoneInfo("Asia/Shanghai")


class BatchRequest(BaseModel):
    """所有当前持仓使用相同开发、验证区间，研究本金不可混成真实本金。"""

    model_config = ConfigDict(extra="forbid")
    development_start: date
    development_end: date
    validation_start: date
    validation_end: date


class ObservationRequest(BaseModel):
    """用户主动选择保存批次中的一个候选，不自动按收益最大采用。"""

    model_config = ConfigDict(extra="forbid")
    research_batch_id: int
    instrument_code: str = Field(pattern=r"^\d{6}$")
    candidate_key: str


class ExecutionRequest(BaseModel):
    """人工依据券商记录确认成交所属日期与累计委托。"""

    model_config = ConfigDict(extra="forbid")
    curr_date: date
    entrust_no: str = Field(min_length=1, max_length=100)
    confirmed_trade_date: date
    confirm_plan_preceded_trade: StrictBool
    confirmation_note: str = Field(min_length=1, max_length=1000)


class SkipRequest(BaseModel):
    """主动偏离必须留下解释，不推断未关联等于未执行。"""

    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=1000)


def current_holdings(db):
    """最新账户快照只提供范围与实际份额，不提供研究资金权重。"""
    latest, rows = latest_holdings(db)
    return latest, [
        r
        for r in rows
        if r.current_amount > 0 and db.get(Instrument, r.instrument_code)
    ]


def source_rows(db, code, end, collected_before=None):
    """按源日期读取完整历史，盘前决策另限制首次或修订采集时间。"""
    statement = select(Candle).where(Candle.code == code, Candle.date <= end)
    if collected_before is not None:
        statement = statement.where(Candle.collected_at <= collected_before)
    return [
        {
            "trade_date": str(row.date),
            **{
                key: str(getattr(row, key)) if getattr(row, key) is not None else None
                for key in ("open", "high", "low", "close", "adjusted_close", "volume")
            },
            "collected_at": row.collected_at.isoformat(),
            "source_updated_at": row.source_updated_at,
        }
        for row in db.scalars(statement.order_by(Candle.date))
    ]


def factor_snapshot(rows, dividends):
    """输出可追溯含息趋势、20日动量与年化波动；不足预热明确为空。"""
    values = features(rows, dividends, 60)
    if not values:
        return None
    value, average = values[-1]
    returns = [
        float(values[i][0] / values[i - 1][0] - 1)
        for i in range(max(1, len(values) - 20), len(values))
    ]
    return {
        "as_of": rows[-1]["trade_date"],
        "trend_above_ma60": value > average if average is not None else None,
        "momentum20": float(value / values[-21][0] - 1) if len(values) > 20 else None,
        "volatility20": pstdev(returns) * sqrt(252) if len(returns) == 20 else None,
        "source": "本地原始收盘与已核验现金分红构造的因果含息指数",
        "note": "趋势控制持有状态，动量仅确认入场；波动供观察。估值、恐贪及国家队为背景，不赋予交易权重。",
    }


@router.get("/catalog")
def catalog():
    """默认范围只有当前真实持仓，给出共同区间建议及数据准备状态。"""
    with Session() as db:
        latest, held = current_holdings(db)
        items, starts, ends = [], [], []
        for row in held:
            instrument = db.get(Instrument, row.instrument_code)
            prices = source_rows(
                db, row.instrument_code, now().date() - timedelta(days=1)
            )
            source = db.get(BacktestSource, row.instrument_code)
            start = prices[60]["trade_date"] if len(prices) > 60 else None
            end = prices[-1]["trade_date"] if prices else None
            factors, factor_warning = None, None
            if not source or not prices:
                factor_warning = "行情或权益来源缺失，暂不计算含息因子"
            elif source.checked_through_date < date.fromisoformat(
                prices[-1]["trade_date"]
            ):
                factor_warning = "权益核验未覆盖最新行情，暂不计算含息因子"
            else:
                try:
                    validate_market(prices, source.corporate_actions)
                    factors = factor_snapshot(
                        prices, source.corporate_actions["dividends"]
                    )
                except ValueError as exc:
                    factor_warning = str(exc)
            if start:
                starts.append(start)
            if end:
                ends.append(end)
            items.append(
                {
                    "instrument_code": row.instrument_code,
                    "instrument_name": instrument.name,
                    "actual_quantity": str(row.current_amount),
                    "available_quantity": str(row.enable_amount),
                    "holding_date": str(row.data_date),
                    "first_date": prices[0]["trade_date"] if prices else None,
                    "research_start": start,
                    "last_date": end,
                    "source_checked_through": str(source.checked_through_date)
                    if source
                    else None,
                    "factors": factors,
                    "factor_warning": factor_warning,
                }
            )
        suggested = None
        if held and len(starts) == len(held) and len(ends) == len(held):
            days, _ = trading_days(max(starts), min(ends))
            if len(days) >= 40:
                split = max(20, int(len(days) * 0.7))
                suggested = {
                    "development_start": days[0],
                    "development_end": days[split - 1],
                    "validation_start": days[split],
                    "validation_end": days[-1],
                }
        previous, _ = trading_days(
            now().date() - timedelta(days=15), now().date() - timedelta(days=1)
        )
        warnings = []
        if not held:
            warnings.append("尚无有效正持仓快照，请先在投资复盘同步账户")
        if latest and previous and latest < date.fromisoformat(previous[-1]):
            warnings.append(
                "真实持仓快照早于最近完整交易日；研究范围可能已变化，请先同步"
            )
        return {
            "as_of": latest,
            "initial_cash_per_etf": str(RESEARCH_CASH),
            "items": items,
            "candidates": CANDIDATES,
            "costs": COSTS,
            "suggested": suggested,
            "warnings": warnings,
            "rule_note": "每只ETF独立50000元研究资金；真实仓位与交易以同步为准。当前持仓回看历史属于事后选择样本。",
        }


def batch_payload(batch):
    """返回冻结批次；不根据当前持仓或行情悄悄修改历史。"""
    return {
        "id": batch.research_batch_id,
        "created_at": batch.created_at.astimezone(TZ),
        "input": batch.input_snapshot,
        "input_sha256": batch.input_sha256,
        "result": batch.result_snapshot,
    }


def research_period(db, code, start, end):
    """逐候选保留尝试与失败，半资金复用25000元引擎账户再加储备。"""
    tracks, failures = [], []
    for candidate in CANDIDATES:
        try:
            with db.begin_nested():
                capital = RESEARCH_CASH * candidate["allocation"] / 100
                experiment = execute_backtest(
                    BacktestRequest(
                        instrument_code=code,
                        strategy_key=candidate["strategy_key"],
                        parameters=candidate["parameters"],
                        start_date=start,
                        end_date=end,
                        initial_cash=capital,
                        **COSTS,
                    ),
                    db,
                )
                account = experiment["result"]["strategy"]
                benchmark = experiment["result"]["benchmark"]
                if capital < RESEARCH_CASH:
                    account = with_reserve(account, RESEARCH_CASH - capital)
                    benchmark = with_reserve(benchmark, RESEARCH_CASH - capital)
                tracks.append(
                    {
                        **deepcopy(candidate),
                        "experiment_id": experiment["id"],
                        **account,
                        "diagnostics": diagnostics(account),
                        "same_exposure_benchmark": benchmark
                        if capital < RESEARCH_CASH
                        else None,
                    }
                )
        except HTTPException as exc:
            failures.append(
                {
                    "key": candidate["key"],
                    "name": candidate["name"],
                    "reason": str(exc.detail),
                }
            )
    return {
        "status": "blocked" if failures else "available",
        "tracks": tracks,
        "failures": failures,
        "pareto_keys": pareto_keys(tracks) if not failures else [],
    }


def combine_accounts(accounts):
    """汇总等额独立研究账户，资金、净值和费用均按组合整体计算。"""
    initial = RESEARCH_CASH * len(accounts)
    calendars = [[row["trade_date"] for row in a["daily"]] for a in accounts]
    if any(calendar != calendars[0] for calendar in calendars):
        raise ValueError("对象交易日范围不一致，不能汇总")
    daily, peak, underwater, longest = [], initial, 0, 0
    for group in zip(*(a["daily"] for a in accounts), strict=True):
        equity = sum((Decimal(r["equity"]) for r in group), Decimal(0))
        underwater = underwater + 1 if equity < peak else 0
        longest = max(longest, underwater)
        peak = max(peak, equity)
        daily.append(
            {
                "trade_date": group[0]["trade_date"],
                "equity": str(equity),
                "nav": float(equity / initial),
                "drawdown": float(equity / peak - 1),
                "position_weight": float(
                    sum((Decimal(r["market_value"]) for r in group), Decimal(0))
                    / equity
                ),
            }
        )
    trades = [trade for a in accounts for trade in a["trades"]]
    detail = [diagnostics(a) for a in accounts]
    return {
        "daily": daily,
        "metrics": metrics(daily, trades, initial),
        "diagnostics": {
            "longest_underwater_days": longest,
            "time_in_market": sum(r["position_weight"] > 0 for r in daily) / len(daily),
            "completed_rounds": sum(d["completed_rounds"] for d in detail),
            "open_rounds": sum(d["open_rounds"] for d in detail),
            "sample_warning": "组合轮次为各ETF完整退出轮次之和，不代表独立样本",
        },
    }


def portfolio_result(instruments, period):
    """只汇总范围完整、共同日历一致的独立账户；不回填真实持仓权重。"""
    if not instruments or any(
        item["periods"][period]["status"] != "available" for item in instruments
    ):
        return {
            "status": "blocked",
            "reason": "有ETF缺失或失败，不能将幸存对象冒充完整持仓组合",
            "tracks": [],
        }
    tracks = []
    try:
        for candidate in CANDIDATES:
            accounts = [
                next(
                    t
                    for t in item["periods"][period]["tracks"]
                    if t["key"] == candidate["key"]
                )
                for item in instruments
            ]
            combined = combine_accounts(accounts)
            if candidate["allocation"] == 50:
                combined["same_exposure_benchmark"] = combine_accounts(
                    [a["same_exposure_benchmark"] for a in accounts]
                )
            tracks.append(
                {"key": candidate["key"], "name": candidate["name"], **combined}
            )
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc), "tracks": []}
    return {
        "status": "available",
        "initial_cash": str(RESEARCH_CASH * len(instruments)),
        "tracks": tracks,
        "pareto_keys": pareto_keys(tracks),
    }


@router.post("/batches")
def create_batch(body: BatchRequest):
    """一次冻结研究范围与全部规则；失败项留存，开发和验证必须不重叠。"""
    if not (
        body.development_start
        <= body.development_end
        < body.validation_start
        <= body.validation_end
        < now().date()
    ):
        raise HTTPException(422, "开发和验证区间必须依次排列、不重叠且结束早于今天")
    for start, end in (
        (body.development_start, body.development_end),
        (body.validation_start, body.validation_end),
    ):
        try:
            days, _ = trading_days(start, end)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if len(days) < 2:
            raise HTTPException(422, "每个区间至少需要两个交易日")
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        latest, held = current_holdings(db)
        if not held:
            raise HTTPException(422, "当前没有已同步的正持仓ETF，不创建空研究")
        snapshot = {
            **body.model_dump(mode="json"),
            "holdings_as_of": str(latest),
            "initial_cash_per_etf": str(RESEARCH_CASH),
            "instruments": [
                {
                    "instrument_code": r.instrument_code,
                    "instrument_name": db.get(Instrument, r.instrument_code).name,
                    "actual_quantity_at_creation": str(r.current_amount),
                    "holding_collected_at": r.collected_at.isoformat(),
                }
                for r in held
            ],
            "candidates": [
                {
                    **deepcopy(c),
                    "strategy_version": get_strategy(c["strategy_key"])["metadata"][
                        "version"
                    ],
                }
                for c in CANDIDATES
            ],
            "costs": COSTS,
            "research_version": RESEARCH_VERSION,
            "engine_version": ENGINE_VERSION,
        }
        items = []
        for row in snapshot["instruments"]:
            periods = {
                name: research_period(db, row["instrument_code"], start, end)
                for name, start, end in (
                    ("development", body.development_start, body.development_end),
                    ("validation", body.validation_start, body.validation_end),
                )
            }
            items.append({**row, "periods": periods})
        batch = StrategyResearchBatch(
            created_at=now(),
            input_snapshot=snapshot,
            input_sha256=digest(snapshot),
            result_snapshot={
                "instruments": items,
                "portfolio": {
                    p: portfolio_result(items, p) for p in ("development", "validation")
                },
                "warnings": [
                    "范围由今天持仓事后选定，不代表历史时点已知研究对象。",
                    "验证结果一旦被查看，再据此调参就不再是未见样本；所有批次独立保留。",
                    "不预设回撤让步阈值；非支配标记不代表推荐或适合实盘。",
                    "真实收益请通过投资复盘按真实现金流核算，不能把50000元模拟净值当作实盘收益。",
                ],
            },
        )
        db.add(batch)
        db.commit()
        return batch_payload(batch)


@router.get("/batches")
def batches():
    """批次列表只读摘要，完整净值按需加载。"""
    with Session() as db:
        return [
            {
                "id": b.research_batch_id,
                "created_at": b.created_at,
                "input": b.input_snapshot,
            }
            for b in db.scalars(
                select(StrategyResearchBatch)
                .where(StrategyResearchBatch.input_snapshot["kind"].as_string().is_distinct_from("single_etf"))
                .order_by(StrategyResearchBatch.research_batch_id.desc())
                .limit(30)
            )
        ]


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int):
    """读取原研究快照，不触发外部接口或更新实验。"""
    with Session() as db:
        batch = db.get(StrategyResearchBatch, batch_id)
        if not batch or batch.input_snapshot.get("kind") == "single_etf":
            raise HTTPException(404, "持仓候选研究批次不存在；单ETF策略请从我的策略查看")
        return batch_payload(batch)


def observation_payload(row):
    """观察规则版本与状态分开展示。"""
    return {
        "id": row.observation_id,
        "research_batch_id": row.research_batch_id,
        "strategy_version_id": row.strategy_version_id,
        "instrument_code": row.instrument_code,
        "created_at": row.created_at.astimezone(TZ),
        "active": row.active,
        "rule": row.rule_snapshot,
    }


@router.post("/observations")
def adopt(body: ObservationRequest):
    """为某只ETF人工选择规则；新版本自动暂停旧版但不删除历史。"""
    with Session() as db:
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 800000000 + int(body.instrument_code)},
        )
        batch = db.get(StrategyResearchBatch, body.research_batch_id)
        if not batch or digest(batch.input_snapshot) != batch.input_sha256:
            raise HTTPException(404, "研究批次不存在或输入校验失败")
        if batch.input_snapshot.get("kind") == "single_etf":
            raise HTTPException(422, "单ETF策略版本须通过我的策略显式启用，不作为固定持仓候选采用")
        item = next(
            (
                r
                for r in batch.result_snapshot["instruments"]
                if r["instrument_code"] == body.instrument_code
            ),
            None,
        )
        candidate = next(
            (
                c
                for c in batch.input_snapshot["candidates"]
                if c["key"] == body.candidate_key
            ),
            None,
        )
        if (
            not item
            or not candidate
            or any(
                item["periods"][p]["status"] != "available"
                for p in ("development", "validation")
            )
        ):
            raise HTTPException(422, "只能采用该批次开发与验证均完整的ETF候选")
        for old in db.scalars(
            select(StrategyObservation).where(
                StrategyObservation.instrument_code == body.instrument_code,
                StrategyObservation.active.is_(True),
            )
        ):
            old.active = False
        db.flush()
        observation = StrategyObservation(
            research_batch_id=body.research_batch_id,
            instrument_code=body.instrument_code,
            created_at=now(),
            active=True,
            rule_snapshot={
                **deepcopy(candidate),
                "initial_cash": str(RESEARCH_CASH),
                "costs": batch.input_snapshot["costs"],
                "research_version": batch.input_snapshot["research_version"],
                "engine_version": batch.input_snapshot["engine_version"],
            },
        )
        db.add(observation)
        db.commit()
        return observation_payload(observation)


@router.get("/observations")
def observations():
    """返回观察版本，不自动为任何ETF采用候选。"""
    with Session() as db:
        return [
            observation_payload(r)
            for r in db.scalars(
                select(StrategyObservation).order_by(
                    StrategyObservation.observation_id.desc()
                )
            )
        ]


@router.post("/observations/{observation_id}/pause")
def pause(observation_id: int):
    """暂停只影响后续生成，不回写既有信号。"""
    with Session() as db:
        row = db.scalar(
            select(StrategyObservation)
            .where(StrategyObservation.observation_id == observation_id)
            .with_for_update()
        )
        if not row:
            raise HTTPException(404, "观察版本不存在")
        row.active = False
        db.commit()
        return observation_payload(row)


def execution_window(at):
    """只允许为下一个尚未开盘交易日建计划，交易日开盘后不补当天计划。"""
    at = at.astimezone(TZ)
    days, _ = trading_days(
        at.date() - timedelta(days=20), at.date() + timedelta(days=20)
    )
    future = [d for d in days if d >= str(at.date())]
    if not future:
        raise ValueError("交易日历没有可执行日期")
    execution = date.fromisoformat(future[0])
    if execution == at.date() and at.time().replace(tzinfo=None) >= at.replace(
        hour=9, minute=30, second=0, microsecond=0
    ).time().replace(tzinfo=None):
        raise ValueError("交易日已开盘，禁止补写当日信号；等待下一次盘前生成")
    cutoff = date.fromisoformat(days[days.index(str(execution)) - 1])
    return cutoff, execution


def make_plan(db, observation, at, cutoff, execution):
    """复用注册规则，冻结已采集证据，研究目标与实际可卖份额独立核对。"""
    if observation.strategy_version_id is not None:
        from app.strategy_plans import make_saved_plan

        return make_saved_plan(db, observation, at, cutoff, execution)
    rule = observation.rule_snapshot
    if (
        rule["strategy_version"]
        != get_strategy(rule["strategy_key"])["metadata"]["version"]
        or rule["research_version"] != RESEARCH_VERSION
        or rule["engine_version"] != ENGINE_VERSION
    ):
        raise ValueError("观察版本与当前代码不同，请基于新研究重新采用")
    code = observation.instrument_code
    source = db.get(BacktestSource, code)
    if not source or source.checked_through_date < cutoff or source.collected_at > at:
        raise ValueError("分红权益未核验到决策日，或采集时刻晚于生成时间")
    rows = source_rows(db, code, cutoff, at)
    if not rows or rows[-1]["trade_date"] != str(cutoff):
        raise ValueError("上一完整交易日行情缺失或尚未采集，禁止用旧价格生成计划")
    validate_market(rows, source.corporate_actions)
    prepared = get_strategy(rule["strategy_key"])["prepare"](
        rows, source.corporate_actions["dividends"], rule["parameters"]
    )
    decision = prepared[-1]["decision"]
    if decision is None:
        raise ValueError("规则预热不足")
    latest, snapshot_rows = latest_holdings(db)
    if latest is None or latest < cutoff or latest > at.date():
        raise ValueError("真实持仓快照缺失或过期，请先同步账户")
    sync = db.scalar(
        select(AccountSyncRun)
        .where(AccountSyncRun.account_id == 1)
        .order_by(AccountSyncRun.sync_run_id.desc())
        .limit(1)
    )
    if (
        not sync
        or sync.status != "success"
        or sync.ended_at is None
        or sync.ended_at > at
    ):
        raise ValueError("最近账户同步未完整成功，不能确认真实仓位")
    holding = next((row for row in snapshot_rows if row.instrument_code == code), None)
    if holding and holding.collected_at > at:
        raise ValueError("持仓记录晚于信号生成时刻")
    actual = holding.current_amount if holding else Decimal(0)
    available = holding.enable_amount if holding else Decimal(0)
    reference = Decimal(rows[-1]["close"])
    capital = RESEARCH_CASH * rule["allocation"] / 100
    price = reference * (1 + Decimal(rule["costs"]["slippage_bps"]) / 10000)
    target = int(capital / (price * 100)) * 100 if decision.target else 0
    while (
        target
        and Decimal(target) * price
        + max(
            Decimal(rule["costs"]["minimum_commission"]),
            Decimal(target) * price * Decimal(rule["costs"]["commission_rate"]),
        )
        > capital
    ):
        target -= 100
    prior = db.scalar(
        select(StrategySignal)
        .where(
            StrategySignal.observation_id == observation.observation_id,
            StrategySignal.execution_date < execution,
        )
        .order_by(StrategySignal.execution_date.desc())
        .limit(1)
    )
    position_basis = (
        "本轮首次建仓按研究预算及决策收盘参考整手估算；实际成交价和现金路径另核对"
    )
    if prior and decision.target and prior.plan_snapshot["target_weight"] > 0:
        subsequent = [
            point["decision"]
            for row, point in zip(rows, prepared, strict=True)
            if row["trade_date"] > str(prior.data_cutoff)
        ]
        if all(point is not None and point.target == 1 for point in subsequent):
            target = prior.plan_snapshot["target_quantity"]
            position_basis = "持有条件持续成立，沿用本轮建仓参考份额；不因涨跌每日再平衡，不动用储备补仓"
    delta = Decimal(target) - actual
    action = "buy" if delta > 0 else "sell" if delta < 0 else "hold"
    requested = abs(delta)
    executable = min(requested, available) if action == "sell" else requested
    # 研究目标按整手，实际份额保留源精度；买入只能整手，可用份额限制体现T+1。
    if action == "buy":
        executable = Decimal(int(executable / 100) * 100)
    evidence = {
        "rows": rows,
        "actions": source.corporate_actions,
        "source_collected_at": source.collected_at.isoformat(),
        "source_sha256": source.source_sha256,
        "holding_date": str(latest),
        "holding_collected_at": holding.collected_at.isoformat() if holding else None,
        "rule": rule,
        "generated_at": at.isoformat(),
    }
    plan = {
        "action": action,
        "target_weight": decision.target * rule["allocation"] / 100,
        "target_quantity": target,
        "position_basis": position_basis,
        "initial_cash": str(RESEARCH_CASH),
        "reference_price": str(reference),
        "actual_quantity": str(actual),
        "available_quantity": str(available),
        "holding_date": str(latest),
        "requested_quantity": str(requested),
        "planned_quantity": str(executable),
        "reason": decision.reason,
        "indicators": prepared[-1]["indicators"],
        "factors": factor_snapshot(rows, source.corporate_actions["dividends"]),
        "funding_check_required": action == "buy",
        "availability_limited": executable < requested,
        "warnings": (
            ["未同步可用现金，买入计划必须先核对资金；参考收盘价不是可成交订单"]
            if action == "buy"
            else []
        )
        + (
            ["真实可用份额不足，可能受T+1或冻结限制；不将不足部分视为已执行"]
            if action == "sell" and executable < requested
            else []
        ),
        "input_sha256": digest(evidence),
    }
    return plan, evidence


@router.post("/signals/generate")
def generate_signals():
    """手动及调度共用，逐观察版本隔离失败，同版本执行日幂等。"""
    at = now()
    created, existing, blocked = [], [], []
    try:
        execution_window(at)
    except ValueError as exc:
        return {"created": [], "existing": [], "blocked": [{"reason": str(exc)}]}
    with Session() as db:
        ids = list(
            db.scalars(
                select(StrategyObservation.observation_id).where(
                    StrategyObservation.active.is_(True)
                )
            )
        )
    for observation_id in ids:
        with Session() as db:
            db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            try:
                observation = db.scalar(
                    select(StrategyObservation)
                    .where(StrategyObservation.observation_id == observation_id)
                    .with_for_update()
                )
            except OperationalError as exc:
                if getattr(exc.orig, "sqlstate", None) != "40001":
                    raise
                blocked.append(
                    {
                        "observation_id": observation_id,
                        "reason": "观察状态在生成期间发生变化，请重新确认运行版本后重试",
                    }
                )
                continue
            if not observation.active:
                continue
            try:
                at = now()
                cutoff, execution = execution_window(at)
                prior = db.scalar(
                    select(StrategySignal).where(
                        StrategySignal.observation_id == observation_id,
                        StrategySignal.execution_date == execution,
                    )
                )
                if prior:
                    existing.append(signal_payload(db, prior))
                    continue
                plan, evidence = make_plan(db, observation, at, cutoff, execution)
                published_at = now()
                if execution_window(published_at) != (cutoff, execution):
                    raise ValueError("计算跨过执行窗口，不能补写已过去的日计划")
                evidence["data_read_started_at"] = evidence["generated_at"]
                evidence["generated_at"] = published_at.isoformat()
                plan["input_sha256"] = digest(evidence)
                signal = StrategySignal(
                    observation_id=observation_id,
                    instrument_code=observation.instrument_code,
                    generated_at=published_at,
                    data_cutoff=cutoff,
                    execution_date=execution,
                    plan_snapshot=plan,
                    evidence_snapshot=evidence,
                )
                db.add(signal)
                db.commit()
                created.append(signal_payload(db, signal))
            except IntegrityError as exc:
                # 重复生成可能在等待观察锁前取得旧快照；唯一约束保证只发布一次。
                if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != "uq_strategy_signal_observation_day":
                    raise
                db.rollback()
                saved = db.scalar(select(StrategySignal).where(
                    StrategySignal.observation_id == observation_id,
                    StrategySignal.execution_date == execution,
                ))
                if saved is None:
                    raise
                existing.append(signal_payload(db, saved))
            except ValueError as exc:
                blocked.append(
                    {
                        "observation_id": observation_id,
                        "instrument_code": observation.instrument_code,
                        "reason": str(exc),
                    }
                )
    return {"created": created, "existing": existing, "blocked": blocked}


def signal_payload(db, signal):
    """按最新累计成交重算执行状态；未关联保持未确认，不推断实际是否跟随。"""
    links = []
    total = Decimal(0)
    for link in db.scalars(
        select(StrategyExecutionLink).where(
            StrategyExecutionLink.signal_id == signal.signal_id
        )
    ):
        trade = db.get(
            AccountEntrust, (link.account_id, link.curr_date, link.entrust_no)
        )
        amount = trade.business_amount if trade else Decimal(0)
        valid = bool(
            trade
            and trade.instrument_code == signal.instrument_code
            and trade.entrust_side
            == ("1" if signal.plan_snapshot["action"] == "buy" else "2")
        )
        if valid:
            total += amount
        links.append(
            {
                "id": link.execution_link_id,
                "curr_date": link.curr_date,
                "entrust_no": link.entrust_no,
                "confirmed_at": link.confirmed_at,
                "confirmed_trade_date": link.confirmed_trade_date,
                "confirmation_note": link.confirmation_note,
                "confirmed_amount": str(link.confirmed_amount),
                "current_amount": str(amount),
                "source_revised": not valid or amount != link.confirmed_amount,
                "source_valid": valid,
            }
        )
    wanted = Decimal(signal.plan_snapshot["requested_quantity"])
    status = (
        "skipped"
        if signal.skip_note
        else "quantity_unknown"
        if signal.plan_snapshot.get("quantity_status") == "unknown"
        else "no_action"
        if wanted == 0
        else "unconfirmed"
        if not links
        else "none"
        if total == 0
        else "partial"
        if total < wanted
        else "complete"
        if total == wanted
        else "excess"
    )
    return {
        "id": signal.signal_id,
        "observation_id": signal.observation_id,
        "instrument_code": signal.instrument_code,
        "generated_at": signal.generated_at,
        "data_cutoff": signal.data_cutoff,
        "execution_date": signal.execution_date,
        "plan": signal.plan_snapshot,
        "skip_note": signal.skip_note,
        "skipped_at": signal.skipped_at,
        "execution": {
            "status": status,
            "confirmed_quantity": str(total),
            "links": links,
        },
    }


@router.get("/signals")
def signals():
    """读取最近计划与人工确认状态，不输出账户凭据。"""
    with Session() as db:
        return [
            signal_payload(db, row)
            for row in db.scalars(
                select(StrategySignal)
                .order_by(StrategySignal.signal_id.desc())
                .limit(200)
            )
        ]


@router.get("/signals/{signal_id}/candidates")
def execution_candidates(signal_id: int):
    """同标的方向日期仅为匹配候选，委托时间不是成交时间证明。"""
    with Session() as db:
        signal = db.get(StrategySignal, signal_id)
        if not signal:
            raise HTTPException(404, "计划不存在")
        rows = db.scalars(
            select(AccountEntrust).where(
                AccountEntrust.account_id == 1,
                AccountEntrust.instrument_code == signal.instrument_code,
                AccountEntrust.curr_date == signal.execution_date,
                AccountEntrust.entrust_side
                == ("1" if signal.plan_snapshot["action"] == "buy" else "2"),
                AccountEntrust.business_amount > 0,
            )
        )
        return (
            [
                {
                    "curr_date": r.curr_date,
                    "entrust_no": r.entrust_no,
                    "quantity": str(r.business_amount),
                    "price": str(r.business_price),
                    "fee_amount": str(r.fee_amount),
                    "note": "累计委托候选；需依据券商成交明细确认实际成交日和计划在先",
                }
                for r in rows
            ]
            if signal.plan_snapshot["action"] in ("buy", "sell") and signal.plan_snapshot.get("quantity_status") != "unknown"
            else []
        )


@router.post("/signals/{signal_id}/link")
def link_execution(signal_id: int, body: ExecutionRequest):
    """人工关联单条累计委托，一条委托不能重复算作多个计划执行。"""
    with Session() as db:
        signal = db.scalar(
            select(StrategySignal)
            .where(StrategySignal.signal_id == signal_id)
            .with_for_update()
        )
        if not signal:
            raise HTTPException(404, "计划不存在")
        trade = db.get(AccountEntrust, (1, body.curr_date, body.entrust_no))
        if (
            not body.confirm_plan_preceded_trade
            or signal.skip_note
            or signal.plan_snapshot["action"] not in ("buy", "sell")
            or signal.plan_snapshot.get("quantity_status") == "unknown"
            or body.confirmed_trade_date != signal.execution_date
            or body.confirmed_trade_date > now().astimezone(TZ).date()
            or (
                body.confirmed_trade_date == now().astimezone(TZ).date()
                and (now().astimezone(TZ).hour, now().astimezone(TZ).minute) < (9, 30)
            )
            or signal.generated_at.astimezone(TZ)
            >= signal.generated_at.astimezone(TZ).replace(
                year=signal.execution_date.year,
                month=signal.execution_date.month,
                day=signal.execution_date.day,
                hour=9,
                minute=30,
                second=0,
                microsecond=0,
            )
            or not body.confirmation_note.strip()
            or not trade
            or trade.instrument_code != signal.instrument_code
            or trade.entrust_side
            != ("1" if signal.plan_snapshot["action"] == "buy" else "2")
            or trade.business_amount <= 0
        ):
            raise HTTPException(422, "成交日期、方向、计划时点或人工依据不符，不能关联")
        link = StrategyExecutionLink(
            signal_id=signal_id,
            account_id=1,
            curr_date=body.curr_date,
            entrust_no=body.entrust_no,
            confirmed_trade_date=body.confirmed_trade_date,
            confirmed_at=now(),
            confirmed_amount=trade.business_amount,
            confirmation_note=body.confirmation_note.strip(),
        )
        db.add(link)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "该累计委托已关联计划，不能重复归属") from None
        return signal_payload(db, signal)


@router.post("/signals/{signal_id}/skip")
def skip_signal(signal_id: int, body: SkipRequest):
    """明确记录主动不执行原因；已有关联成交的计划不能再标成跳过。"""
    with Session() as db:
        row = db.scalar(
            select(StrategySignal)
            .where(StrategySignal.signal_id == signal_id)
            .with_for_update()
        )
        if not row:
            raise HTTPException(404, "计划不存在")
        linked = db.scalar(
            select(StrategyExecutionLink)
            .where(StrategyExecutionLink.signal_id == signal_id)
            .limit(1)
        )
        if linked or not body.note.strip() or row.skip_note:
            raise HTTPException(409, "计划已有成交关联、已跳过或缺少有效原因")
        row.skip_note, row.skipped_at = body.note.strip(), now()
        db.commit()
        return signal_payload(db, row)


@router.get("/observations/{observation_id}/review")
def review_observation(observation_id: int):
    """采用后区间用当前数据重算规则，不将此前回看或实际成交混成前向业绩。"""
    from app.backtest import run_backtest

    with Session() as db:
        observation = db.get(StrategyObservation, observation_id)
        if not observation:
            raise HTTPException(404, "观察版本不存在")
        if observation.strategy_version_id is not None:
            from app.strategy_plans import review_saved_observation

            return review_saved_observation(db, observation, now())
        adopted_at = observation.created_at.astimezone(TZ)
        source = db.get(BacktestSource, observation.instrument_code)
        rows = source_rows(
            db,
            observation.instrument_code,
            now().astimezone(TZ).date() - timedelta(days=1),
        )
        # 采用发生在收盘后时，只能从下个交易日开始，不能拿采用前的开盘算收益。
        after = [r for r in rows if r["trade_date"] > str(adopted_at.date())]
        base = {
            "adopted_at": adopted_at,
            "label": "采用后按当前数据重算的规则表现；非真实成交收益、非当时生成信号的前向业绩",
        }
        if not after:
            return {
                **base,
                "status": "pending",
                "reason": "采用后尚无完整交易日行情，等待真实观察积累",
            }
        if not source or source.checked_through_date < date.fromisoformat(
            after[-1]["trade_date"]
        ):
            return {**base, "status": "blocked", "reason": "权益核验尚未覆盖观察区间"}
        rule = observation.rule_snapshot
        if (
            rule["strategy_version"]
            != get_strategy(rule["strategy_key"])["metadata"]["version"]
            or rule["engine_version"] != ENGINE_VERSION
        ):
            return {**base, "status": "blocked", "reason": "观察规则版本与当前代码不符"}
        try:
            validate_market(rows, source.corporate_actions)
            capital = RESEARCH_CASH * rule["allocation"] / 100
            settings = {
                "strategy_key": rule["strategy_key"],
                "parameters": rule["parameters"],
                "initial_cash": str(capital),
                **rule["costs"],
                "start_date": after[0]["trade_date"],
                "end_date": after[-1]["trade_date"],
            }
            result = run_backtest(rows, source.corporate_actions["dividends"], settings)
            if capital < RESEARCH_CASH:
                result = {
                    k: with_reserve(v, RESEARCH_CASH - capital)
                    for k, v in result.items()
                }
            return {
                **base,
                "status": "available",
                "result": result,
                "diagnostics": diagnostics(result["strategy"]),
                "data_cutoff": rows[-1]["trade_date"],
            }
        except ValueError as exc:
            return {**base, "status": "blocked", "reason": str(exc)}


def collect_signals(run_id):
    """独立任务5记录08:30计划生成结果，失败不阻塞行情或账户同步。"""
    from app.models import Run
    from app.strategy_plans import prepare_signal_dependencies

    dependency_errors = prepare_signal_dependencies()
    result = generate_signals()
    result["blocked"].extend(dependency_errors)
    logs = [
        {"status": "failed", "code": r.get("instrument_code"), "message": r["reason"]}
        for r in result["blocked"]
    ]
    logs.append(
        {
            "status": "success",
            "message": f"新增{len(result['created'])}份计划；已有{len(result['existing'])}份；无观察版本时不自动采用策略",
        }
    )
    with Session() as db:
        run = db.get(Run, run_id)
        run.status = "partial" if result["blocked"] else "success"
        run.ended_at, run.logs = now(), logs
        db.commit()


@router.get("/job")
def signal_job():
    """读取独立日计划任务配置和运行日志。"""
    from app.jobs import next_run
    from app.models import Job, Run

    with Session() as db:
        job = db.get(Job, 5)
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": True,
            "runs": [
                {
                    "id": r.id,
                    "status": r.status,
                    "trigger": r.trigger,
                    "started_at": r.started_at,
                    "ended_at": r.ended_at,
                    "logs": r.logs,
                }
                for r in db.scalars(
                    select(Run).where(Run.job_id == 5).order_by(Run.id.desc()).limit(10)
                )
            ],
        }


class SignalJobRequest(BaseModel):
    """每日计划时间按北京时间设置，迟到仍受开盘门槛约束。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.put("/job")
def update_signal_job(body: SignalJobRequest):
    """保存任务5配置，不改变其他采集任务。"""
    from app.models import Job

    with Session() as db:
        job = db.get(Job, 5)
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@router.post("/job/run", status_code=202)
def run_signal_job():
    """手动触发独立任务5，运行日志与数据采集隔离。"""
    from app.jobs import launch

    run_id = launch("manual", job_id=5)
    if run_id is None:
        raise HTTPException(409, "日计划任务正在运行")
    return {"run_id": run_id}
