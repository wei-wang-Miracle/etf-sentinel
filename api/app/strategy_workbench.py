"""当前策略目录、同ETF研究比较与显式采用接口。"""

from datetime import UTC, date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select, text

from app.algorithm_templates import (
    SHARED_WARMUP_BARS,
    supports_template,
    template_snapshot,
)
from app.backtest import ENGINE_VERSION
from app.backtest_data import DATA_VERSION
from app.backtest_routes import backtest_instruments, digest
from app.collection import now
from app.db import Session
from app.factor_strategy_templates import (
    FACTOR_TEMPLATES,
    factor_template_snapshot,
    is_factor_template,
    prepare_factor_template,
)
from app.models import (
    BacktestRun,
    BacktestSource,
    Candle,
    Instrument,
    InstrumentStrategyAssignment,
    ResearchFactor,
    ResearchStrategyFactor,
    ResearchStrategyScope,
    StrategyComparison,
    StrategyComparisonFactor,
)
from app.research_factors import STRATEGIES
from app.strategy_inputs import (
    external_snapshot,
    factor_external_snapshot,
    market_snapshot,
)
from app.strategy_research import diagnostics

router = APIRouter(prefix="/strategies", tags=["策略研究"])


class CommonSettings(BaseModel):
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


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument_code: str = Field(pattern=r"^[0-9]{6}$")
    start_date: date
    end_date: date
    strategies: list[str] = Field(min_length=1, max_length=12)


class AdoptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comparison_id: int
    strategy_id: str = Field(min_length=1, max_length=64)
    replace_active: StrictBool = False


def _instrument_history_bounds(db, today):
    """汇总各ETF的分类与已核验/拆后历史边界，用于计算不同策略的最早可回测起点。"""
    instruments = {row.code: row for row in db.scalars(select(Instrument))}
    sources = {row.instrument_code: row for row in db.scalars(select(BacktestSource))}
    dates_by_code = {code: [] for code in instruments}
    for code, day in db.execute(select(Candle.code, Candle.date).order_by(Candle.code, Candle.date)):
        if code in dates_by_code:
            dates_by_code[code].append(day)

    bounds = {}
    for code, instrument in instruments.items():
        source = sources.get(code)
        dates = dates_by_code.get(code, [])
        verified = [
            day
            for day in dates
            if source and day < today and day <= source.checked_through_date
        ]
        split = (
            max(
                (
                    date.fromisoformat(event["effective_date"])
                    for event in source.corporate_actions["splits"]
                    if verified and event["effective_date"] <= str(verified[-1])
                ),
                default=None,
            )
            if source
            else None
        )
        usable = [day for day in verified if split is None or day > split]
        bounds[code] = {
            "category": instrument.research_category or "未分类",
            "verified": verified,
            "usable": usable,
        }
    return bounds


def _earliest_start_for_strategy(strategy_id, bound):
    """按策略类型返回指定ETF的最早可用起始日期；预热不足返回None。"""
    verified = bound["verified"]
    usable = bound["usable"]
    if is_factor_template(strategy_id):
        min_warmup = FACTOR_TEMPLATES[strategy_id]["min_warmup_bars"]
        if len(verified) <= min_warmup or len(usable) <= 1:
            return None
        return str(max(verified[min_warmup], usable[1]))
    if len(usable) <= SHARED_WARMUP_BARS:
        return None
    return str(usable[SHARED_WARMUP_BARS])


def _resolve_strategy_scope(db, strategy_id, instrument_code):
    """按数据库作用域表匹配ETF对应的研究绑定结论；分类绑定的优先级高于通用绑定。"""
    all_scopes = list(db.scalars(select(ResearchStrategyScope)))
    if not all_scopes:
        return False
    instrument = db.get(Instrument, instrument_code)
    category = (instrument.research_category if instrument else None) or "未分类"
    strategy_scopes = [item for item in all_scopes if item.strategy_id == strategy_id]
    for scope in strategy_scopes:
        if scope.scope_type == "category" and scope.category_name == category:
            return scope
    for scope in strategy_scopes:
        if scope.scope_type == "universal":
            return scope
    return False


def strategy_catalog(db, instrument_code=None):
    instruments = backtest_instruments(algorithm_warmup=SHARED_WARMUP_BARS)
    bounds = _instrument_history_bounds(db, now().date())
    for item in instruments:
        code = item["instrument_code"]
        item["research_category"] = bounds.get(code, {}).get("category", "未分类")
    supported_codes = sorted(item["instrument_code"] for item in instruments)
    factors = {row.factor_id: row for row in db.scalars(select(ResearchFactor))}
    relations = list(
        db.scalars(
            select(ResearchStrategyFactor).order_by(
                ResearchStrategyFactor.display_order
            )
        )
    )
    all_scopes = list(db.scalars(select(ResearchStrategyScope)))
    has_scope_table = bool(all_scopes)

    catalog = []
    for strategy_id, definition in STRATEGIES.items():
        if definition.get("research_only"):
            continue
        min_warmup = (
            FACTOR_TEMPLATES[strategy_id]["min_warmup_bars"]
            if is_factor_template(strategy_id)
            else SHARED_WARMUP_BARS
        )
        scopes_for_strategy = [
            scope for scope in all_scopes if scope.strategy_id == strategy_id
        ]
        if has_scope_table:
            universal_scope = next(
                (scope for scope in scopes_for_strategy if scope.scope_type == "universal"),
                None,
            )
            cat_scopes = {
                scope.category_name: scope
                for scope in scopes_for_strategy
                if scope.scope_type == "category"
            }
            scope_type = "universal" if universal_scope else "category"
            bound_categories = sorted(cat_scopes)
            supported = []
            adoptable_instruments = []
            for code in supported_codes:
                category = bounds.get(code, {}).get("category", "未分类")
                matched_scope = cat_scopes.get(category) or universal_scope
                if matched_scope is None:
                    continue
                supported.append(code)
                if matched_scope.adoptable:
                    adoptable_instruments.append(code)
            evidence_by_category = {
                scope.category_name: {
                    "scope_type": scope.scope_type,
                    "research_version": scope.research_version,
                    "evidence_tier": scope.evidence_tier,
                    "adoptable": scope.adoptable,
                    "evidence_summary": scope.evidence_summary,
                }
                for scope in scopes_for_strategy
            }
            adoptable_flag = bool(adoptable_instruments)
        else:
            # 数据库作用域表为空时不再回退放行代码内策略，确保清空数据库即对应空策略目录。
            scope_type = "category"
            bound_categories = []
            supported = []
            adoptable_flag = False
            adoptable_instruments = []
            evidence_by_category = {}

        earliest_start_by_instrument = {
            code: _earliest_start_for_strategy(
                strategy_id,
                bounds.get(code, {"category": "未分类", "verified": [], "usable": []}),
            )
            for code in supported
        }
        strategy_factors = []
        for relation in relations:
            if relation.strategy_id != strategy_id:
                continue
            factor = factors[relation.factor_id]
            strategy_factors.append(
                {
                    "id": factor.factor_id,
                    "name": factor.factor_name,
                    "category": factor.category,
                    "meaning": factor.meaning,
                    "role": relation.role,
                }
            )
        catalog.append(
            {
                "id": strategy_id,
                "name": definition["name"],
                "description": definition["description"],
                "adoptable": adoptable_flag,
                "scope_type": scope_type,
                "bound_categories": bound_categories,
                "adoptable_instruments": adoptable_instruments,
                "min_warmup_bars": min_warmup,
                "earliest_start_by_instrument": earliest_start_by_instrument,
                "evidence_by_category": evidence_by_category,
                "factors": strategy_factors,
                "supported_instruments": supported,
            }
        )
    return {
        "instruments": instruments,
        "strategies": catalog,
        "assignments": [
            assignment_payload(row)
            for row in db.scalars(select(InstrumentStrategyAssignment))
            if instrument_code is None or row.instrument_code == instrument_code
        ],
        "engine_version": ENGINE_VERSION,
    }


def _candidate(strategy, code, *, allow_unadoptable=False, db=None):
    definition = STRATEGIES.get(strategy)
    if not definition or definition.get("research_only"):
        raise HTTPException(422, "策略不可用或未覆盖这只ETF")
    scope = _resolve_strategy_scope(db, strategy, code) if db is not None else None
    if scope is False:
        raise HTTPException(422, "该策略未绑定到当前ETF所属研究分类，不可比较或采用")
    can_adopt = scope.adoptable if scope is not None else definition.get("adoptable", True)
    if not allow_unadoptable and not can_adopt:
        raise HTTPException(422, "该策略在当前分类尚未达到研究采用门槛，仅用于比较观察")
    if is_factor_template(strategy):
        template = factor_template_snapshot(strategy, code)
        return {
            "id": strategy,
            "name": template["name"],
            "factor_template": template,
            "allocation": 100,
        }
    if not supports_template(strategy, "1.0.0", code):
        raise HTTPException(422, "策略不可用或未覆盖这只ETF")
    template = template_snapshot(strategy, "1.0.0", code)
    return {
        "id": strategy,
        "name": template["name"],
        "template": template,
        "allocation": 100,
    }


def execute_candidate(candidate, snapshot):
    from app.backtest import run_backtest
    from app.strategies import get_strategy

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
    template = candidate.get("template")
    factor_template = candidate.get("factor_template")
    active_template = template or factor_template
    min_warmup = (
        factor_template["min_warmup_bars"]
        if factor_template
        else SHARED_WARMUP_BARS
    )
    warmup_rows = market.get("warmup_rows") if factor_template else None
    warmup_bars = (len(warmup_rows) - len(rows) + begin) if warmup_rows else begin
    if active_template and warmup_bars < min_warmup:
        raise ValueError(
            f"回测开始前需要至少{min_warmup}个有效交易日预热，请调晚开始日期"
        )
    strategy_key = (
        "factor_strategy"
        if factor_template
        else "algorithm_template"
        if template
        else "hold"
    )
    candidate_external = snapshot["external"]
    if factor_template and warmup_rows:
        candidate_external = {
            **snapshot["external"],
            "warmup_rows": warmup_rows,
            "warmup_dividends": market.get("warmup_dividends"),
        }
    settings = {
        **common,
        "strategy_key": strategy_key,
        "parameters": {
            "template": active_template,
            "external": candidate_external,
            "decision_start": rows[begin - 1]["trade_date"],
            "slippage_bps": common["slippage_bps"],
        }
        if active_template
        else {},
    }
    if active_template:
        from app.algorithm_templates import prepare_template

        decisions = (
            prepare_factor_template(
                rows, market["actions"]["dividends"], settings["parameters"]
            )
            if factor_template
            else prepare_template(
                rows, market["actions"]["dividends"], settings["parameters"]
            )
        )
        missing = next(
            (
                (row, point)
                for row, point in zip(
                    rows[begin - 1 :], decisions[begin - 1 :], strict=True
                )
                if point["decision"] is None
            ),
            None,
        )
        if missing:
            raise ValueError(f"{missing[0]['trade_date']}策略所需因子数据或预热不足")
    result = run_backtest(rows, market["actions"]["dividends"], settings)
    account = result["strategy"]
    return (
        result,
        account,
        {
            **market,
            "settings": settings,
            "engine_version": ENGINE_VERSION,
            "strategy_implementation": get_strategy(settings["strategy_key"])[
                "metadata"
            ]["version"],
        },
    )


def comparison_payload(row, detail=True):
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
        rows = row.input_snapshot["market"].get("rows", [])
        payload["market_rows"] = rows
        payload["data_cutoff"] = rows[-1]["trade_date"] if rows else None
        payload["note"] = (
            "历史模拟，不代表真实成交或未来收益；实验快照不可作为历史策略启用。"
        )
    return payload


@router.get("/catalog")
def catalog(instrument_code: str | None = None):
    with Session() as db:
        return strategy_catalog(db, instrument_code)


@router.post("/comparisons")
def compare(body: ComparisonRequest):
    if body.start_date > body.end_date or body.end_date >= now().date():
        raise HTTPException(422, "起止日期无效，截止日须早于今天")
    strategy_ids = list(dict.fromkeys(body.strategies))
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if not db.get(Instrument, body.instrument_code):
            raise HTTPException(404, "ETF不在配置范围内")
        candidates = []
        for strategy_id in strategy_ids:
            strategy = STRATEGIES.get(strategy_id)
            if not strategy or strategy.get("research_only"):
                raise HTTPException(422, "策略不可用或仅供离线研究")
            candidates.append(
                _candidate(
                    strategy_id,
                    body.instrument_code,
                    allow_unadoptable=True,
                    db=db,
                )
            )
        candidates.append({"id": "hold", "name": "一直持有", "allocation": 100})
        settings = CommonSettings(**body.model_dump(exclude={"strategies"})).model_dump(
            mode="json"
        )
        has_factor = any(c.get("factor_template") for c in candidates)
        try:
            market = market_snapshot(
                db,
                body.instrument_code,
                body.end_date,
                interval_start=body.start_date,
                allow_verified_suspensions=True,
                include_warmup_rows=has_factor,
            )
        except ValueError as exc:
            market = {"error": str(exc)}
        valuation_metrics = {
            c["template"]["rule"]["value_metric"]
            for c in candidates
            if c.get("template") and c["template"]["rule"]["value_metric"] != "none"
        }
        external = external_snapshot(
            db, body.instrument_code, valuation_metrics, body.end_date
        )
        factor_requirements = {
            req
            for c in candidates
            if c.get("factor_template")
            for req in c["factor_template"]["external_requirements"]
        }
        if factor_requirements:
            external.update(
                factor_external_snapshot(
                    db, body.instrument_code, body.end_date, factor_requirements
                )
            )
        snapshot = {
            "settings": settings,
            "candidates": candidates,
            "market": market,
            "external": external,
            "engine_version": ENGINE_VERSION,
            "strategy_implementation": "current-code",
            "data_version": DATA_VERSION,
        }
        tracks = []
        for candidate in candidates:
            track = {
                "key": candidate["id"],
                "strategy_id": candidate["id"],
                "name": candidate["name"],
                "status": "failed",
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
                track["reason"] = str(exc)
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
        db.flush()
        for track in tracks:
            strategy_id = track["strategy_id"]
            if strategy_id == "hold" or track["status"] != "success":
                continue
            for factor_id, _ in STRATEGIES[strategy_id]["factors"]:
                db.add(
                    StrategyComparisonFactor(
                        comparison_id=comparison.comparison_id,
                        strategy_id=strategy_id,
                        factor_id=factor_id,
                    )
                )
        db.commit()
        return comparison_payload(comparison)


@router.get("/comparisons")
def comparisons(instrument_code: str | None = None):
    with Session() as db:
        query = (
            select(StrategyComparison)
            .order_by(StrategyComparison.comparison_id.desc())
            .limit(20)
        )
        if instrument_code:
            query = query.where(StrategyComparison.instrument_code == instrument_code)
        return [comparison_payload(row, detail=False) for row in db.scalars(query)]


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: int):
    with Session() as db:
        row = db.get(StrategyComparison, comparison_id)
        if not row:
            raise HTTPException(404, "策略比较记录不存在")
        return comparison_payload(row)


@router.post("/comparisons/{comparison_id}/verify")
def verify_comparison(comparison_id: int):
    with Session() as db:
        row = db.get(StrategyComparison, comparison_id)
        if not row:
            raise HTTPException(404, "策略比较记录不存在")
        snapshot = row.input_snapshot
        if (
            snapshot["engine_version"] != ENGINE_VERSION
            or snapshot["data_version"] != DATA_VERSION
            or digest(snapshot) != row.input_sha256
        ):
            raise HTTPException(
                409, "比较输入摘要或引擎/数据口径已变化，当前代码不能复算该实验"
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


def assignment_payload(row):
    return {
        "id": row.assignment_id,
        "instrument_code": row.instrument_code,
        "strategy_id": row.strategy_id,
        "active": row.active,
        "comparison_id": row.comparison_id,
        "adopted_at": row.created_at.astimezone(UTC),
    }


@router.post("/adopt")
def adopt(body: AdoptionRequest):
    with Session() as db:
        comparison = db.get(StrategyComparison, body.comparison_id)
        if (
            not comparison
            or digest(comparison.input_snapshot) != comparison.input_sha256
        ):
            raise HTTPException(422, "比较记录不存在或输入摘要异常")
        track = next(
            (
                item
                for item in comparison.result_snapshot["tracks"]
                if item["strategy_id"] == body.strategy_id
            ),
            None,
        )
        if not track or track["status"] != "success" or body.strategy_id == "hold":
            raise HTTPException(422, "只能采用本次成功回测中的现行策略")
        strategy = STRATEGIES.get(body.strategy_id)
        if not strategy or strategy.get("research_only"):
            raise HTTPException(422, "该策略仅供离线研究")
        scope = _resolve_strategy_scope(db, body.strategy_id, comparison.instrument_code)
        if scope is False:
            raise HTTPException(422, "该策略未绑定到当前ETF所属研究分类，不可采用")
        can_adopt = (
            scope.adoptable if scope is not None else strategy.get("adoptable", True)
        )
        if not can_adopt:
            raise HTTPException(422, "该策略在当前分类尚未达到研究采用门槛，仅用于比较观察")
        db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": 800000000 + int(comparison.instrument_code)},
        )
        assignment = db.scalar(
            select(InstrumentStrategyAssignment)
            .where(
                InstrumentStrategyAssignment.instrument_code
                == comparison.instrument_code
            )
            .with_for_update()
        )
        if (
            assignment
            and assignment.strategy_id != body.strategy_id
            and not body.replace_active
        ):
            raise HTTPException(409, "该ETF已有当前策略，确认替换后再采用")
        if (
            assignment
            and assignment.active
            and assignment.strategy_id == body.strategy_id
        ):
            return assignment_payload(assignment)
        model_start = db.scalar(
            select(Candle.date)
            .where(Candle.code == comparison.instrument_code)
            .order_by(Candle.date.desc())
            .limit(1)
        )
        if model_start is None:
            raise HTTPException(409, "缺少行情，无法确定采用后的模型起点")
        settings = {
            **comparison.input_snapshot["settings"],
            "decision_start": str(model_start),
        }
        adopted_at = now()
        if assignment is None:
            assignment = InstrumentStrategyAssignment(
                instrument_code=comparison.instrument_code,
                strategy_id=body.strategy_id,
                active=True,
                comparison_id=comparison.comparison_id,
                created_at=adopted_at,
                settings_snapshot=settings,
            )
            db.add(assignment)
        else:
            assignment.strategy_id = body.strategy_id
            assignment.active = True
            assignment.comparison_id = comparison.comparison_id
            assignment.created_at = adopted_at
            assignment.settings_snapshot = settings
        db.commit()
        return assignment_payload(assignment)


@router.post("/{instrument_code}/pause")
def pause(instrument_code: str = Path(pattern=r"^[0-9]{6}$")):
    with Session() as db:
        assignment = db.scalar(
            select(InstrumentStrategyAssignment)
            .where(InstrumentStrategyAssignment.instrument_code == instrument_code)
            .with_for_update()
        )
        if not assignment:
            raise HTTPException(404, "该ETF尚无当前策略")
        assignment.active = False
        db.commit()
        return assignment_payload(assignment)
