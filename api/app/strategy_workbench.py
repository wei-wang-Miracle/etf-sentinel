"""单ETF中文策略草稿、不可变版本与统一比较接口，不代替真实交易。"""

from copy import deepcopy
from datetime import UTC, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.backtest import ENGINE_VERSION, metrics, money, run_backtest
from app.backtest_data import DATA_VERSION
from app.backtest_routes import catalog as backtest_catalog
from app.backtest_routes import digest
from app.collection import now
from app.db import Session
from app.models import (
    BacktestRun,
    Instrument,
    SavedStrategy,
    SavedStrategyVersion,
    SentimentCategory,
    StrategyComparison,
    StrategyDraft,
    StrategyObservation,
    StrategyResearchBatch,
)
from app.strategies import get_strategy
from app.strategy_conditions import (
    CONDITION_VERSION,
    CONDITIONS,
    evidence_type,
    normalize_rule,
    prepare_conditions,
)
from app.strategy_inputs import condition_coverage, external_snapshot, market_snapshot
from app.strategy_research import RESEARCH_VERSION, diagnostics

router = APIRouter(prefix="/strategies", tags=["单ETF策略流程"])


class CommonSettings(BaseModel):
    """统一比较假设，百分率采用小数、滑点采用基点。

    Attributes:
        instrument_code: 唯一ETF主体。
        start_date: 模拟账户建立日期，之前行情仅预热。
        end_date: 最后计价日期，必须早于今天。
        initial_cash: 人民币完整研究本金，包含保留现金。
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    instrument_code: str = Field(pattern=r"^[0-9]{6}$")
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


class CurrentRule(BaseModel):
    """尚未保存的命名配置，由条件引擎进一步检查业务结构。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    rule: dict


class ComparisonRequest(CommonSettings):
    """同ETF具体版本与可选当前草稿的统一重算请求。"""

    current: CurrentRule | None = None
    version_ids: list[StrictInt] = Field(default_factory=list, max_length=100)


class SaveRequest(BaseModel):
    """只从成功比较轨道保存版本，不接受客户端伪造回测结果。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    instrument_code: str = Field(pattern=r"^[0-9]{6}$")
    comparison_id: StrictInt
    track_key: str
    strategy_id: StrictInt | None = None


class DraftRequest(CurrentRule):
    """可恢复编辑草稿；settings保留输入中间态，不用于直接启用。"""

    settings: dict
    strategy_id: StrictInt | None = None


class EnableRequest(BaseModel):
    """替换已有运行策略必须由调用方明确确认。"""

    model_config = ConfigDict(extra="forbid")
    replace_active: StrictBool = False


def _require_instrument(db, code):
    """拒绝用指数或配置外标的建立策略身份。"""
    if not db.get(Instrument, code):
        raise HTTPException(404, "ETF不在配置范围内")


def _validate(rule):
    """将条件校验转换为可读接口输入错误。"""
    try:
        return normalize_rule(rule)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/catalog")
def catalog():
    """提供条件元数据与ETF行情覆盖，页面加载不访问外部来源。"""
    original = backtest_catalog()
    with Session() as db:
        categories = [
            {"key": c.category_key, "name": c.category_name}
            for c in db.scalars(
                select(SentimentCategory).order_by(SentimentCategory.category_key)
            )
        ]
    return {
        "instruments": original["instruments"],
        "conditions": CONDITIONS,
        "sentiment_categories": categories,
        "engine_version": ENGINE_VERSION,
        "condition_version": CONDITION_VERSION,
    }


@router.get("/coverage")
def coverage(instrument_code: str):
    """返回三态条件覆盖，具体回测仍逐日核验。"""
    with Session() as db:
        _require_instrument(db, instrument_code)
        return condition_coverage(db, instrument_code)


@router.get("/drafts/{instrument_code}")
def get_draft(instrument_code: str):
    """读取当前ETF草稿；没有草稿返回空，不借用其他ETF内容。"""
    with Session() as db:
        _require_instrument(db, instrument_code)
        draft = db.get(StrategyDraft, instrument_code)
        return draft.draft_snapshot if draft else None


@router.put("/drafts/{instrument_code}")
def put_draft(instrument_code: str, body: DraftRequest):
    """保存编辑内容，与不可变版本和启用规则隔离。"""
    with Session() as db:
        _require_instrument(db, instrument_code)
        snapshot = body.model_dump(mode="json")
        if body.strategy_id is not None:
            saved = db.get(SavedStrategy, body.strategy_id)
            if not saved or saved.instrument_code != instrument_code:
                raise HTTPException(422, "草稿原策略与ETF不一致")
        if body.settings.get("instrument_code", instrument_code) != instrument_code:
            raise HTTPException(422, "草稿设置与ETF不一致")
        statement = insert(StrategyDraft).values(
            instrument_code=instrument_code, updated_at=now(), draft_snapshot=snapshot
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["instrument_code"],
                set_={
                    "updated_at": statement.excluded.updated_at,
                    "draft_snapshot": statement.excluded.draft_snapshot,
                },
            )
        )
        db.commit()
        return snapshot


def _reserve(account, reserve, initial):
    """按完整本金加入零息储备，不向交易子账户补资或每日再平衡。"""
    result, peak = deepcopy(account), initial
    for row in result["daily"]:
        equity = money(Decimal(row["equity"]) + reserve)
        peak = max(peak, equity)
        row.update(
            cash=str(money(Decimal(row["cash"]) + reserve)),
            equity=str(equity),
            nav=float(equity / initial),
            drawdown=float(equity / peak - 1),
            position_weight=float(Decimal(row["market_value"]) / equity),
        )
    result["metrics"] = metrics(result["daily"], result["trades"], initial)
    return result


def execute_candidate(candidate, snapshot):
    """从冻结输入运行一条候选；失败由调用方保留，不污染其他候选。

    Args:
        candidate: 命名规则或持有参照及投入比例。
        snapshot: 统一市场、权益、外部因子、日期与成本。

    Returns:
        原引擎结果、包含完整本金的比较账户、独立回测输入快照。

    Raises:
        ValueError: 行情、预热、外部条件或版本无效。
    """
    market, common = snapshot["market"], snapshot["settings"]
    if "error" in market:
        raise ValueError(market["error"])
    rows = market["rows"]
    if common["start_date"] < rows[0]["trade_date"]:
        raise ValueError("起始日期早于本地行情覆盖")
    begin = next(
        (
            i
            for i, row in enumerate(rows)
            if common["start_date"] <= row["trade_date"] <= common["end_date"]
        ),
        None,
    )
    if begin is None or begin < 1:
        raise ValueError("区间没有完整交易日或缺少前一交易日预热")
    initial = Decimal(common["initial_cash"])
    allocated = money(initial * Decimal(candidate["allocation"]) / 100)
    settings = {
        **common,
        "initial_cash": str(allocated),
        "strategy_key": "custom_conditions" if candidate.get("rule") else "hold",
        "parameters": {
            "rule": candidate["rule"],
            "external": snapshot["external"],
            "decision_start": rows[begin - 1]["trade_date"],
        }
        if candidate.get("rule")
        else {},
    }
    if candidate.get("rule"):
        signals = prepare_conditions(
            rows, market["actions"]["dividends"], settings["parameters"]
        )
        missing = next(
            (
                (row, point)
                for row, point in zip(
                    rows[begin - 1 :], signals[begin - 1 :], strict=True
                )
                if point["decision"] is None
            ),
            None,
        )
        if missing:
            row, point = missing
            names = [
                c["label"]
                for side in ("buy", "sell")
                for c in point["indicators"][side]
                if c["satisfied"] is None
            ]
            raise ValueError(
                f"{row['trade_date']}条件数据或预热不足：{'、'.join(dict.fromkeys(names))}"
            )
    result = run_backtest(rows, market["actions"]["dividends"], settings)
    account = (
        _reserve(result["strategy"], initial - allocated, initial)
        if allocated != initial
        else result["strategy"]
    )
    run_input = {
        **market,
        "settings": settings,
        "engine_version": ENGINE_VERSION,
        "strategy_version": get_strategy(settings["strategy_key"])["metadata"][
            "version"
        ],
    }
    return result, account, run_input


def comparison_payload(row, detail=True):
    """返回统一比较及其失败状态，完整输入只保留在本地库。"""
    payload = {
        "id": row.comparison_id,
        "instrument_code": row.instrument_code,
        "created_at": row.created_at.astimezone(UTC),
        "settings": row.input_snapshot["settings"],
        "input_sha256": row.input_sha256,
        "complete": row.result_snapshot["complete"],
    }
    if detail:
        payload.update(row.result_snapshot)
        payload["market_rows"] = row.input_snapshot["market"].get("rows", [])
        payload["data_cutoff"] = (
            row.input_snapshot["market"].get("rows", [{}])[-1].get("trade_date")
        )
        payload["note"] = (
            "历史模拟，非真实成交收益；修订历史研究未证明原时点可得，不与严格历史验证混为同一种证据。"
        )
    return payload


@router.post("/comparisons")
def compare(body: ComparisonRequest):
    """统一条件重算所选版本和当前草稿，保存成功及失败对象。

    输入由同一REPEATABLE READ事务冻结；重算不覆盖原版本、原实验或启用状态。
    """
    if body.start_date > body.end_date or body.end_date >= now().date():
        raise HTTPException(422, "起止日期无效，截止日须早于今天")
    if not body.current and not body.version_ids:
        raise HTTPException(422, "请选择至少一条策略或当前配置")
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        _require_instrument(db, body.instrument_code)
        candidates = []
        if body.current:
            current_rule = _validate(body.current.rule)
            if not body.current.name.strip():
                raise HTTPException(422, "策略名称不可为空")
            candidates.append(
                {
                    "key": "current",
                    "name": body.current.name.strip(),
                    "rule": current_rule,
                    "allocation": current_rule["allocation"],
                }
            )
        for version_id in dict.fromkeys(body.version_ids):
            version = db.get(SavedStrategyVersion, version_id)
            if (
                not version
                or db.get(SavedStrategy, version.strategy_id).instrument_code
                != body.instrument_code
            ):
                raise HTTPException(422, "所选策略版本不存在或不属于同一只ETF")
            candidates.append(
                {
                    "key": f"version:{version_id}",
                    "name": f"{version.strategy_name} · V{version.version_number}",
                    "version_id": version_id,
                    "rule": version.configuration["rule"],
                    "allocation": version.configuration["rule"]["allocation"],
                }
            )
        candidates.append({"key": "hold", "name": "一直持有", "allocation": 100})
        if any(c["allocation"] == 50 for c in candidates):
            candidates.append(
                {"key": "hold_half", "name": "半资金持有", "allocation": 50}
            )
        settings = body.model_dump(mode="json", exclude={"current", "version_ids"})
        try:
            market = market_snapshot(db, body.instrument_code, body.end_date)
        except ValueError as exc:
            market = {"error": str(exc)}
        rules = [c["rule"] for c in candidates if c.get("rule")]
        external = external_snapshot(db, body.instrument_code, rules, body.end_date)
        snapshot = {
            "settings": settings,
            "candidates": candidates,
            "market": market,
            "external": external,
            "engine_version": ENGINE_VERSION,
            "condition_version": CONDITION_VERSION,
            "condition_definitions": CONDITIONS,
            "data_version": DATA_VERSION,
        }
        tracks = []
        for candidate in candidates:
            track = {
                "key": candidate["key"],
                "name": candidate["name"],
                "version_id": candidate.get("version_id"),
                "rule": candidate.get("rule"),
                "allocation": candidate["allocation"],
                "evidence_type": evidence_type(candidate["rule"])
                if candidate.get("rule")
                else "historical",
            }
            try:
                result, account, run_input = execute_candidate(candidate, snapshot)
                run = BacktestRun(
                    instrument_code=body.instrument_code,
                    strategy_key=run_input["settings"]["strategy_key"],
                    created_at=now(),
                    input_sha256=digest(run_input),
                    input_snapshot=run_input,
                    result_snapshot=result,
                )
                db.add(run)
                db.flush()
                track.update(
                    status="success",
                    backtest_id=run.backtest_run_id,
                    account=account,
                    diagnostics=diagnostics(account, Decimal(settings["initial_cash"])),
                )
            except ValueError as exc:
                track.update(status="failed", reason=str(exc))
            tracks.append(track)
        comparison = StrategyComparison(
            instrument_code=body.instrument_code,
            created_at=now(),
            input_sha256=digest(snapshot),
            input_snapshot=snapshot,
            result_snapshot={
                "tracks": tracks,
                "complete": all(t["status"] == "success" for t in tracks),
            },
        )
        db.add(comparison)
        db.commit()
        return comparison_payload(comparison)


@router.get("/comparisons")
def comparisons(instrument_code: str | None = None):
    """读取最近二十次统一比较概要，支持按ETF过滤。"""
    with Session() as db:
        query = (
            select(StrategyComparison)
            .order_by(StrategyComparison.comparison_id.desc())
            .limit(20)
        )
        if instrument_code is not None:
            query = query.where(StrategyComparison.instrument_code == instrument_code)
        return [comparison_payload(row, detail=False) for row in db.scalars(query)]


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: int):
    """回看原比较，不读取最新行情覆盖原结果。"""
    with Session() as db:
        row = db.get(StrategyComparison, comparison_id)
        if not row:
            raise HTTPException(404, "策略比较记录不存在")
        return comparison_payload(row)


@router.post("/comparisons/{comparison_id}/verify")
def verify_comparison(comparison_id: int):
    """只用原输入复算比较账户，版本不符或摘要变化明确拒绝。"""
    with Session() as db:
        row = db.get(StrategyComparison, comparison_id)
        if not row:
            raise HTTPException(404, "策略比较记录不存在")
        snapshot = row.input_snapshot
        if (
            snapshot["engine_version"] != ENGINE_VERSION
            or snapshot["condition_version"] != CONDITION_VERSION
            or snapshot["data_version"] != DATA_VERSION
            or digest(snapshot) != row.input_sha256
        ):
            raise HTTPException(
                409, "比较输入摘要或引擎／条件／数据版本不一致，需要对应代码复算"
            )
        identical = True
        for candidate, track in zip(
            snapshot["candidates"], row.result_snapshot["tracks"], strict=True
        ):
            try:
                _, account, _ = execute_candidate(candidate, snapshot)
                identical = (
                    identical
                    and track["status"] == "success"
                    and account == track["account"]
                )
            except ValueError as exc:
                identical = (
                    identical
                    and track["status"] == "failed"
                    and str(exc) == track["reason"]
                )
        return {"identical": identical, "input_sha256": row.input_sha256}


def version_payload(db, version):
    """显式显示不可变版本与独立观察状态，不由回测结果推断运行。"""
    strategy = db.get(SavedStrategy, version.strategy_id)
    observation = db.scalar(
        select(StrategyObservation)
        .where(StrategyObservation.strategy_version_id == version.strategy_version_id)
        .order_by(StrategyObservation.observation_id.desc())
        .limit(1)
    )
    return {
        "id": version.strategy_version_id,
        "strategy_id": version.strategy_id,
        "name": version.strategy_name,
        "version": version.version_number,
        "instrument_code": strategy.instrument_code,
        "created_at": version.created_at.astimezone(UTC),
        **version.configuration,
        "backtest_id": version.backtest_run_id,
        "comparison_id": version.comparison_id,
        "active": bool(observation and observation.active),
        "observation_id": observation.observation_id if observation else None,
    }


@router.get("")
def versions(instrument_code: str | None = None):
    """读取全部具体版本，列表可按ETF缩小，不隐藏旧版本。"""
    with Session() as db:
        query = (
            select(SavedStrategyVersion)
            .join(SavedStrategy)
            .order_by(SavedStrategyVersion.strategy_version_id.desc())
        )
        if instrument_code is not None:
            query = query.where(SavedStrategy.instrument_code == instrument_code)
        return [version_payload(db, row) for row in db.scalars(query)]


@router.post("")
def save_version(body: SaveRequest):
    """从有效回测保存不可变版本，串行编号且不改变观察状态。"""
    if not body.name.strip():
        raise HTTPException(422, "策略名称不可为空")
    with Session() as db:
        _require_instrument(db, body.instrument_code)
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 810000000 + int(body.instrument_code)},
        )
        comparison = db.get(StrategyComparison, body.comparison_id)
        if (
            not comparison
            or comparison.instrument_code != body.instrument_code
            or digest(comparison.input_snapshot) != comparison.input_sha256
        ):
            raise HTTPException(422, "比较记录不存在、ETF不一致或输入摘要异常")
        track = next(
            (
                t
                for t in comparison.result_snapshot["tracks"]
                if t["key"] == body.track_key
            ),
            None,
        )
        if not track or track["status"] != "success" or not track.get("rule"):
            raise HTTPException(
                422, "只能保存成功回测的自定义策略，参照或失败结果不可保存"
            )
        if body.strategy_id is not None:
            strategy = db.get(SavedStrategy, body.strategy_id)
            if not strategy or strategy.instrument_code != body.instrument_code:
                raise HTTPException(422, "原策略不存在或绑定其他ETF")
        else:
            strategy = SavedStrategy(
                instrument_code=body.instrument_code, created_at=now()
            )
            db.add(strategy)
            db.flush()
        number = (
            db.scalar(
                select(func.max(SavedStrategyVersion.version_number)).where(
                    SavedStrategyVersion.strategy_id == strategy.strategy_id
                )
            )
            or 0
        ) + 1
        version = SavedStrategyVersion(
            strategy_id=strategy.strategy_id,
            version_number=number,
            strategy_name=body.name.strip(),
            created_at=now(),
            configuration={
                "rule": deepcopy(track["rule"]),
                "settings": deepcopy(comparison.input_snapshot["settings"]),
            },
            backtest_run_id=track["backtest_id"],
            comparison_id=comparison.comparison_id,
        )
        db.add(version)
        db.flush()
        db.commit()
        return version_payload(db, version)


@router.post("/{version_id}/enable")
def enable(version_id: int, body: EnableRequest):
    """显式采用具体版本，同ETF运行策略替换须先确认，不回填历史计划。"""
    from app.jobs import next_run
    from app.models import Job
    from app.strategy_lab import execution_window

    with Session() as db:
        version = db.get(SavedStrategyVersion, version_id)
        if not version:
            raise HTTPException(404, "策略版本不存在")
        strategy = db.get(SavedStrategy, version.strategy_id)
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 800000000 + int(strategy.instrument_code)},
        )
        active = list(
            db.scalars(
                select(StrategyObservation)
                .where(
                    StrategyObservation.instrument_code == strategy.instrument_code,
                    StrategyObservation.active.is_(True),
                )
                .with_for_update()
            )
        )
        if active and active[0].strategy_version_id == version_id:
            observation = active[0]
            db.commit()
        else:
            if active and not body.replace_active:
                raise HTTPException(409, "这只ETF已有运行策略，确认替换后再启用")
            run = db.get(BacktestRun, version.backtest_run_id)
            if (
                not run
                or digest(run.input_snapshot) != run.input_sha256
                or run.input_snapshot["engine_version"] != ENGINE_VERSION
                or run.input_snapshot["strategy_version"] != CONDITION_VERSION
            ):
                raise HTTPException(409, "原回测版本或输入不一致，请重新回测并保存新版")
            for old in active:
                old.active = False
            db.flush()
            configuration = version.configuration
            batch_input = {
                "kind": "single_etf",
                "strategy_version_id": version_id,
                "settings": configuration["settings"],
                "rule": configuration["rule"],
                "engine_version": ENGINE_VERSION,
            }
            batch = StrategyResearchBatch(
                created_at=now(),
                input_snapshot=batch_input,
                result_snapshot={
                    "comparison_id": version.comparison_id,
                    "backtest_run_id": version.backtest_run_id,
                },
                input_sha256=digest(batch_input),
            )
            db.add(batch)
            db.flush()
            observation = StrategyObservation(
                research_batch_id=batch.research_batch_id,
                strategy_version_id=version_id,
                instrument_code=strategy.instrument_code,
                created_at=now(),
                active=True,
                rule_snapshot={
                    "key": f"saved:{version_id}",
                    "name": version.strategy_name,
                    "strategy_key": "custom_conditions",
                    "parameters": {
                        "rule": configuration["rule"],
                        "decision_start": run.input_snapshot["settings"]["parameters"][
                            "decision_start"
                        ],
                    },
                    "allocation": configuration["rule"]["allocation"],
                    "initial_cash": configuration["settings"]["initial_cash"],
                    "costs": {
                        key: configuration["settings"][key]
                        for key in ("commission_rate", "minimum_commission", "slippage_bps")
                    },
                    "strategy_version": CONDITION_VERSION,
                    "research_version": RESEARCH_VERSION,
                    "engine_version": ENGINE_VERSION,
                },
            )
            db.add(observation)
            db.flush()
            db.commit()
        from app.strategy_plans import make_saved_plan

        try:
            at = now()
            cutoff, execution = execution_window(at)
            with Session() as preview_db:
                preview_db.connection(
                    execution_options={"isolation_level": "REPEATABLE READ"}
                )
                preview_observation = preview_db.get(
                    StrategyObservation, observation.observation_id
                )
                plan, _ = make_saved_plan(
                    preview_db, preview_observation, at, cutoff, execution
                )
            readiness = {
                "status": "ready",
                "target": plan["rule_target"],
                "reason": plan["reason"],
                "conditions": plan["conditions"],
                "target_quantity": plan["target_quantity"],
                "actual_quantity": plan["actual_quantity"],
                "quantity_status": plan["quantity_status"],
                "data_cutoff": str(cutoff),
            }
        except ValueError as exc:
            readiness = {"status": "waiting", "reason": str(exc)}
        result = version_payload(db, version)
        result.update(readiness=readiness, next_run=next_run(db.get(Job, 5)))
        return result


@router.post("/{version_id}/pause")
def pause(version_id: int):
    """暂停该版本的后续计划，不清空历史和成交关联。"""
    with Session() as db:
        version = db.get(SavedStrategyVersion, version_id)
        if not version:
            raise HTTPException(404, "策略版本不存在")
        strategy = db.get(SavedStrategy, version.strategy_id)
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 800000000 + int(strategy.instrument_code)},
        )
        for observation in db.scalars(
            select(StrategyObservation)
            .where(StrategyObservation.strategy_version_id == version_id)
            .with_for_update()
        ):
            observation.active = False
        db.commit()
        return version_payload(db, version)
