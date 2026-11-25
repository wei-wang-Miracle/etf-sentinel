"""共享算法比较、ETF绑定和盘前信号启用接口。"""

from copy import deepcopy
from datetime import UTC, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import func, select, text

from app.algorithm_templates import (
    SHARED_WARMUP_BARS,
    TEMPLATE_VERSION,
    TURNING_VERSION,
    is_shared_template,
    supports_template,
    template_catalog,
    template_snapshot,
)
from app.backtest import ENGINE_VERSION, run_backtest
from app.backtest_data import DATA_VERSION
from app.backtest_routes import backtest_instruments, digest
from app.collection import now
from app.db import Session
from app.models import (
    BacktestRun,
    Instrument,
    SavedStrategy,
    SavedStrategyVersion,
    StrategyComparison,
    StrategyObservation,
    StrategyResearchBatch,
)
from app.strategies import get_strategy
from app.strategy_inputs import external_snapshot, market_snapshot
from app.strategy_research import diagnostics

router = APIRouter(prefix="/strategies", tags=["算法策略流程"])


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


class TemplateSelection(BaseModel):
    """仅接收算法标识和不可变版本。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)


class ComparisonRequest(BaseModel):
    """在统一ETF、区间和固定成本下比较所选算法。"""

    model_config = ConfigDict(extra="forbid")
    instrument_code: str = Field(pattern=r"^[0-9]{6}$")
    start_date: date
    end_date: date
    templates: list[TemplateSelection] = Field(min_length=1, max_length=12)


class SaveRequest(BaseModel):
    """从成功比较直接绑定算法，ETF和规则均由原始比较确定。"""

    model_config = ConfigDict(extra="forbid")
    comparison_id: StrictInt
    track_key: str


class EnableRequest(BaseModel):
    """替换已有运行策略必须由调用方明确确认。"""

    model_config = ConfigDict(extra="forbid")
    replace_active: StrictBool = False


def _require_instrument(db, code):
    """拒绝用指数或配置外标的建立策略身份。"""
    if not db.get(Instrument, code):
        raise HTTPException(404, "ETF不在配置范围内")


@router.get("/catalog")
def catalog():
    """提供ETF覆盖与服务端冻结的算法模板目录。"""
    instruments = backtest_instruments(algorithm_warmup=SHARED_WARMUP_BARS)
    codes = [row["instrument_code"] for row in instruments]
    return {
        "instruments": instruments,
        "templates": template_catalog(codes),
        "engine_version": ENGINE_VERSION,
        "template_version": TEMPLATE_VERSION,
    }


def execute_candidate(candidate, snapshot):
    """从冻结输入运行一条模板或买入持有轨道。

    Args:
        candidate: 命名模板或持有参照。
        snapshot: 统一市场、权益、外部因子、日期与成本。

    Returns:
        原引擎结果、包含完整本金的比较账户、独立回测输入快照。

    Raises:
        ValueError: 行情、预热、估值数据或模板版本无效。
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
    allocated = initial
    template = candidate.get("template")
    if template and is_shared_template(template["id"], template["version"]) and begin < SHARED_WARMUP_BARS:
        raise ValueError(f"回测开始前需要至少{SHARED_WARMUP_BARS}个有效交易日预热，请调晚开始日期")
    settings = {
        **common,
        "initial_cash": str(allocated),
        "strategy_key": "algorithm_template" if candidate.get("template") else "hold",
        "parameters": {
            "template": candidate["template"],
            "external": snapshot["external"],
            "decision_start": rows[begin - 1]["trade_date"],
            "slippage_bps": common["slippage_bps"],
        }
        if candidate.get("template")
        else {},
    }
    if candidate.get("template"):
        from app.algorithm_templates import prepare_template

        signals = prepare_template(rows, market["actions"]["dividends"], settings["parameters"])
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
                key
                for key, value in point["indicators"].get("buy", {}).items()
                if value is None
            ]
            raise ValueError(
                f"{row['trade_date']}模板因子数据或预热不足：{'、'.join(dict.fromkeys(names))}"
            )
    result = run_backtest(rows, market["actions"]["dividends"], settings)
    account = result["strategy"]
    run_input = {
        **market,
        "settings": settings,
        "engine_version": ENGINE_VERSION,
        "strategy_version": get_strategy(settings["strategy_key"])["metadata"][
            "version"
        ],
    }
    return result, account, run_input


def candidate_diagnostics(candidate: dict, snapshot: dict, account: dict) -> dict:
    """说明模拟账户完整平仓轮次与期末未平仓轮次。"""
    return diagnostics(account, Decimal(snapshot["settings"]["initial_cash"]))


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
    """以同一事务内的行情和权益比较算法，回测不建立绑定。"""
    if body.start_date > body.end_date or body.end_date >= now().date():
        raise HTTPException(422, "起止日期无效，截止日须早于今天")
    selections = dict.fromkeys((item.id, item.version) for item in body.templates)
    candidates = []
    for template_id, version in selections:
        if not supports_template(template_id, version, body.instrument_code):
            raise HTTPException(422, "所选算法不可用或未覆盖这只ETF")
        template = template_snapshot(template_id, version, body.instrument_code)
        name = template["name"]
        if sum(other_id == template_id for other_id, _ in selections) > 1:
            name = f"{name} · {version}"
        candidates.append({
            "key": f"template:{template_id}:{version}", "name": name,
            "template": template, "allocation": 100,
        })
    candidates.append({"key": "hold", "name": "一直持有", "allocation": 100})
    settings = CommonSettings(**body.model_dump(exclude={"templates"})).model_dump(mode="json")
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        _require_instrument(db, body.instrument_code)
        try:
            market = market_snapshot(
                db,
                body.instrument_code,
                body.end_date,
                interval_start=body.start_date,
            )
        except ValueError as exc:
            market = {"error": str(exc)}
        valuation_metrics = {
            candidate["template"]["rule"]["value_metric"]
            for candidate in candidates
            if candidate.get("template")
            and candidate["template"]["rule"]["value_metric"] != "none"
        }
        external = external_snapshot(
            db,
            body.instrument_code,
            valuation_metrics,
            body.end_date,
        )
        snapshot = {
            "settings": settings,
            "candidates": candidates,
            "market": market,
            "external": external,
            "engine_version": ENGINE_VERSION,
            "template_version": TEMPLATE_VERSION,
            "turning_version": TURNING_VERSION,
            "data_version": DATA_VERSION,
        }
        tracks = []
        for candidate in candidates:
            track = {
                "key": candidate["key"],
                "name": candidate["name"],
                "version_id": candidate.get("version_id"),
                "template": candidate.get("template"),
                "allocation": candidate["allocation"],
                "evidence_type": "revised"
                if candidate.get("template", {}).get("rule", {}).get("value_metric", "none") != "none"
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
                    diagnostics=candidate_diagnostics(candidate, snapshot, account),
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
            or snapshot["template_version"] != TEMPLATE_VERSION
            or snapshot["turning_version"] != TURNING_VERSION
            or snapshot["data_version"] != DATA_VERSION
            or digest(snapshot) != row.input_sha256
        ):
            raise HTTPException(
                409, "比较输入摘要或引擎／模板／数据版本不一致，需要对应代码复算"
            )
        identical = True
        for candidate, track in zip(
            snapshot["candidates"], row.result_snapshot["tracks"], strict=True
        ):
            try:
                _, account, _ = execute_candidate(candidate, snapshot)
                if track["status"] == "success":
                    identical = identical and candidate_diagnostics(
                        candidate, snapshot, account
                    ) == track["diagnostics"]
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
        "algorithm_template_id": strategy.algorithm_template_id,
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
    """保存算法与ETF绑定及原回测，重复保存同一结果返回原记录。"""
    with Session() as db:
        comparison = db.get(StrategyComparison, body.comparison_id)
        if not comparison or digest(comparison.input_snapshot) != comparison.input_sha256:
            raise HTTPException(422, "比较记录不存在或输入摘要异常")
        track = next((t for t in comparison.result_snapshot["tracks"] if t["key"] == body.track_key), None)
        if not track or track["status"] != "success" or not track.get("template"):
            raise HTTPException(422, "只能保存成功的算法回测，持有参照或失败结果不可绑定")
        template = track["template"]
        template_id = template["id"]
        code = comparison.instrument_code
        if not supports_template(template_id, template["version"], code):
            raise HTTPException(422, "所选算法不可用或未覆盖这只ETF")
        run = db.get(BacktestRun, track["backtest_id"])
        if (
            not run
            or run.instrument_code != comparison.instrument_code
            or digest(run.input_snapshot) != run.input_sha256
            or run.input_snapshot["settings"]["parameters"]["template"] != template
            or template_snapshot(template_id, template["version"], code) != template
        ):
            raise HTTPException(409, "算法回测快照不一致，请重新回测")
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 810000000 + int(code)})
        strategy = db.scalar(select(SavedStrategy).where(
            SavedStrategy.instrument_code == code, SavedStrategy.algorithm_template_id == template_id,
        ))
        if strategy is None:
            strategy = SavedStrategy(instrument_code=code, algorithm_template_id=template_id, created_at=now())
            db.add(strategy)
            db.flush()
        existing = db.scalar(select(SavedStrategyVersion).where(
            SavedStrategyVersion.strategy_id == strategy.strategy_id,
            SavedStrategyVersion.backtest_run_id == run.backtest_run_id,
        ))
        if existing is not None:
            return version_payload(db, existing)
        number = (db.scalar(select(func.max(SavedStrategyVersion.version_number)).where(
            SavedStrategyVersion.strategy_id == strategy.strategy_id,
        )) or 0) + 1
        version = SavedStrategyVersion(
            strategy_id=strategy.strategy_id, version_number=number,
            strategy_name=template["name"], created_at=now(),
            configuration={"template": deepcopy(template), "settings": deepcopy(comparison.input_snapshot["settings"])},
            backtest_run_id=run.backtest_run_id, comparison_id=comparison.comparison_id,
        )
        db.add(version)
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
            if strategy.algorithm_template_id is None:
                raise HTTPException(422, "历史绑定只供复盘，请重新回测并保存算法")
            if active and not body.replace_active:
                raise HTTPException(409, "这只ETF已有运行策略，确认替换后再启用")
            run = db.get(BacktestRun, version.backtest_run_id)
            if (
                not run
                or digest(run.input_snapshot) != run.input_sha256
                or run.input_snapshot["engine_version"] != ENGINE_VERSION
                or run.input_snapshot["strategy_version"] != TEMPLATE_VERSION
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
                "template": configuration["template"],
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
            from app.models import Candle

            model_start = db.scalar(
                select(func.max(Candle.date)).where(Candle.code == strategy.instrument_code)
            )
            if model_start is None:
                raise HTTPException(409, "本地行情为空，无法初始化模型持仓状态")
            observation = StrategyObservation(
                research_batch_id=batch.research_batch_id,
                strategy_version_id=version_id,
                instrument_code=strategy.instrument_code,
                created_at=now(),
                active=True,
                rule_snapshot={
                    "key": f"saved:{version_id}",
                    "name": version.strategy_name,
                    "strategy_key": "algorithm_template",
                    "parameters": {
                        "template": configuration["template"],
                        "decision_start": str(model_start),
                        "slippage_bps": configuration["settings"]["slippage_bps"],
                    },
                    "initial_cash": configuration["settings"]["initial_cash"],
                    "costs": {
                        key: configuration["settings"][key]
                        for key in ("commission_rate", "minimum_commission", "slippage_bps")
                    },
                    "strategy_version": TEMPLATE_VERSION,
                    "algorithm_version": configuration["template"]["algorithm_version"],
                    "turning_version": configuration["template"]["turning_version"],
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
