"""单ETF策略版本观察的盘前计划与真实执行核对闭环接口。"""

from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.backtest_data import trading_days
from app.backtest_routes import digest
from app.collection import now
from app.db import Session
from app.models import (
    AccountEntrust,
    StrategyExecutionLink,
    StrategyObservation,
    StrategySignal,
)

router = APIRouter(prefix="/strategy-lab", tags=["持仓策略闭环"])
TZ = ZoneInfo("Asia/Shanghai")


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


@router.get("/observations")
def observations():
    """返回观察版本；启用与暂停统一由我的策略管理。"""
    with Session() as db:
        return [
            observation_payload(r)
            for r in db.scalars(
                select(StrategyObservation).order_by(
                    StrategyObservation.observation_id.desc()
                )
            )
        ]


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
    """仅服务我的策略显式启用的单ETF版本；旧持仓候选观察不再生成计划。"""
    from app.strategy_plans import make_saved_plan

    if observation.strategy_version_id is None:
        raise ValueError("旧持仓候选观察已停用，请通过我的策略启用单ETF版本")
    return make_saved_plan(db, observation, at, cutoff, execution)


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
    from app.strategy_plans import review_saved_observation

    with Session() as db:
        observation = db.get(StrategyObservation, observation_id)
        if not observation:
            raise HTTPException(404, "观察版本不存在")
        if observation.strategy_version_id is None:
            return {
                "status": "blocked",
                "reason": "旧持仓候选研究已下线，仅支持我的策略启用的单ETF版本复盘",
            }
        return review_saved_observation(db, observation, now())


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
