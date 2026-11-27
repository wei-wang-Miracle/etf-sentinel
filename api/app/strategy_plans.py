"""单ETF算法模板的盘前证据与参考份额，沿用任务5和人工成交核对。"""

from decimal import ROUND_CEILING, Decimal

from sqlalchemy import select

from app.account_state import latest_holdings
from app.algorithm_templates import prepare_template
from app.backtest_routes import digest
from app.db import Session
from app.models import AccountSyncRun, InstrumentStrategyAssignment, StrategySignal
from app.strategy_inputs import external_snapshot, market_snapshot


def make_assignment_plan(db, assignment, at, cutoff, execution):
    """按当前策略分配计算方向，账户证据不足时保留未知数量。

    Args:
        db: 当前数据库会话。
        assignment: ETF当前策略分配。
        at: 本次生成实际开始时刻，带时区。
        cutoff: 上一完整交易日。
        execution: 尚未开盘的适用交易日。

    Returns:
        计划与完整输入证据；计划并非订单，未知仓位不能伪装零仓。

    Raises:
        ValueError: 策略、行情、权益或估值输入不满足计算要求。
    """
    from app.strategy_workbench import _candidate

    rule = assignment.settings_snapshot
    candidate = _candidate(assignment.strategy_id, assignment.instrument_code)
    template = candidate["template"]
    parameters = {
        "template": template,
        "decision_start": rule["decision_start"],
        "slippage_bps": rule["slippage_bps"],
        "external": {},
    }
    market = market_snapshot(
        db,
        assignment.instrument_code,
        cutoff,
        at,
        interval_start=parameters["decision_start"],
    )
    value_metric = template["rule"]["value_metric"]
    external = external_snapshot(
        db,
        assignment.instrument_code,
        [value_metric] if value_metric != "none" else [],
        cutoff,
        at,
    )
    parameters["external"] = external
    prepared = prepare_template(
        market["rows"], market["actions"]["dividends"], parameters
    )
    if str(cutoff) < parameters["decision_start"]:
        raise ValueError("采用起点之后尚无完整决策行情")
    point = prepared[-1]
    if point["decision"] is None or any(
        p["decision"] is None
        for row, p in zip(market["rows"], prepared, strict=True)
        if row["trade_date"] >= parameters["decision_start"]
    ):
        raise ValueError("算法模板数据缺失、过期或预热不足；不沿用旧方向")
    if market["rows"][-1]["trade_date"] != str(cutoff):
        raise ValueError("上一完整交易日行情缺失或迟到")
    decision = point["decision"]
    source_date, holdings = latest_holdings(db)
    sync = db.scalar(
        select(AccountSyncRun)
        .where(AccountSyncRun.account_id == 1)
        .order_by(AccountSyncRun.sync_run_id.desc())
        .limit(1)
    )
    complete = bool(
        sync
        and sync.status == "success"
        and sync.ended_at
        and sync.ended_at <= at
        and sync.holdings_snapshot
        and sync.ended_at.astimezone(at.tzinfo).date() >= cutoff
    )
    empty_complete = complete and sync.holdings_snapshot["instrument_codes"] == []
    fresh = complete and (
        empty_complete
        or (source_date is not None and cutoff <= source_date <= at.date())
    )
    holding = next(
        (r for r in holdings if r.instrument_code == assignment.instrument_code), None
    )
    if holding and holding.collected_at > at:
        fresh = False
    actual = (holding.current_amount if holding else Decimal(0)) if fresh else None
    available = (holding.enable_amount if holding else Decimal(0)) if fresh else None
    initial = Decimal(rule["initial_cash"])
    capital = initial
    reference = Decimal(market["rows"][-1]["close"])
    price = (
        reference * (1 + Decimal(rule["slippage_bps"]) / 10000) / Decimal("0.001")
    ).to_integral_value(rounding=ROUND_CEILING) * Decimal("0.001")
    target = int(capital / (price * 100)) * 100 if decision.target else 0
    while (
        target
        and target * price
        + max(
            Decimal(rule["minimum_commission"]),
            target * price * Decimal(rule["commission_rate"]),
        )
        > capital
    ):
        target -= 100
    prior = db.scalar(
        select(StrategySignal)
        .where(
            StrategySignal.assignment_id == assignment.assignment_id,
            StrategySignal.generated_at >= assignment.created_at,
            StrategySignal.execution_date < execution,
        )
        .order_by(StrategySignal.execution_date.desc())
        .limit(1)
    )
    continuing = bool(
        prior
        and decision.target
        and prior.plan_snapshot["target_weight"] > 0
        and all(
            p["decision"] is not None and p["decision"].target
            for row, p in zip(market["rows"], prepared, strict=True)
            if row["trade_date"] > str(prior.data_cutoff)
        )
    )
    if continuing:
        target = prior.plan_snapshot["target_quantity"]
    delta = Decimal(target) - actual if actual is not None else None
    action = (
        (
            "buy"
            if delta > 0
            else "sell"
            if delta < 0
            else "hold"
            if decision.target
            else "wait"
        )
        if delta is not None
        else ("buy" if decision.target else "wait")
    )
    requested = abs(delta) if delta is not None else Decimal(0)
    executable = min(requested, available) if action == "sell" else requested
    if action == "buy":
        executable = Decimal(int(executable / 100) * 100)
    evidence = {
        "rows": market["rows"],
        "actions": market["actions"],
        "source": market["source"],
        "external": external,
        "strategy_id": assignment.strategy_id,
        "adopted_at": assignment.created_at.isoformat(),
        "rule": template,
        "generated_at": at.isoformat(),
        "holding_date": str(source_date) if source_date else None,
        "holdings_snapshot": sync.holdings_snapshot if sync else None,
        "actual_quantity": str(actual) if actual is not None else None,
        "available_quantity": str(available) if available is not None else None,
    }
    warnings = []
    if not fresh:
        warnings.append(
            "完整账户快照缺失或过期：方向已计算，数量待核验；未知仓位不当作零仓"
        )
    if action == "buy":
        warnings.append("买入必须人工核验可用现金；研究预算并不代表真实账户现金")
    if action == "sell" and executable < requested:
        warnings.append("真实可用份额不足，可能受T+1或冻结限制")
    return {
        "action": action,
        "rule_target": decision.target,
        "new_trigger": not prior
        or prior.plan_snapshot["target_weight"] != decision.target,
        "target_weight": decision.target,
        "target_quantity": target,
        "position_basis": "持续持有沿用本轮参考份额，不每日调仓；模型参考成本不等于真实持仓成本"
        if continuing
        else "按研究预算和决策收盘估算参考整手，非真实现金路径或订单",
        "initial_cash": str(initial),
        "reference_price": str(reference),
        "quantity_status": "available" if fresh else "unknown",
        "actual_quantity": str(actual) if actual is not None else None,
        "available_quantity": str(available) if available is not None else None,
        "holding_date": str(source_date) if source_date else None,
        "requested_quantity": str(requested),
        "planned_quantity": str(executable),
        "reason": decision.reason,
        "conditions": {
            side: [
                {"label": key, "satisfied": value, "value": value}
                for key, value in point["indicators"][side].items()
            ]
            for side in ("buy", "sell")
        },
        "indicators": point["indicators"],
        "funding_check_required": action == "buy",
        "availability_limited": executable < requested,
        "warnings": warnings,
        "input_sha256": digest(evidence),
    }, evidence


def prepare_signal_dependencies():
    """任务5独立补齐已启用模板的权益和账户，失败返回安全原因。

    仅写本地采集结果；外部行情和账户接口只读，日志不包含凭据。
    """
    from app.account_sync import sync_account
    from app.backtest_routes import refresh_sources
    from app.collection import now
    from app.strategy_lab import execution_window

    with Session() as db:
        codes = list(
            db.scalars(
                select(InstrumentStrategyAssignment.instrument_code).where(
                    InstrumentStrategyAssignment.active.is_(True)
                )
            )
        )
    if not codes:
        return []
    try:
        execution_window(now())
    except ValueError as exc:
        return [{"reason": str(exc)}]
    errors = []
    for code in codes:
        try:
            refresh_sources(code)
        except Exception:  # noqa: BLE001 — 外部依赖边界保留安全摘要，不输出含凭据异常
            errors.append(
                {
                    "instrument_code": code,
                    "reason": "盘前自动更新权益资料失败，请检查数据管理并重试",
                }
            )
    try:
        result = sync_account()
        if result.get("status") != "success":
            errors.append(
                {"reason": "盘前账户同步未完整成功，数量保持待核验；请检查数据管理"}
            )
    except Exception:  # noqa: BLE001 — 账户依赖异常只记录安全摘要，不暴露源请求或凭据
        errors.append(
            {"reason": "盘前自动同步账户失败，数量保持待核验；请检查数据管理"}
        )
    return errors
