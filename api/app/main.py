"""ETF 日行情配置、任务管理与本地行情查询 API。"""

import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import InvalidOperation

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.account_routes import router as account_router
from app.algorithm_templates import SHARED_WARMUP_BARS, turning_events, turning_profile
from app.backtest_data import (
    front_adjusted_ohlc_rows,
    indicator_ohlc_rows,
    validate_market,
)
from app.backtest_routes import router as backtest_router
from app.collection import fetch_rows, now, validate_row
from app.db import Session
from app.index_valuation_routes import router as index_valuation_router
from app.jobs import (
    launch,
    next_run,
    queue_free_backfill,
    recover_interrupted,
    scheduler,
)
from app.market_sentiment_routes import router as market_sentiment_router
from app.models import (
    BacktestSource,
    Candle,
    IndexCandle,
    IndexValuationDaily,
    Instrument,
    InstrumentIndexLink,
    InstrumentSentimentLink,
    Job,
    MarketFearGreedDaily,
    MarketRegimeFactorDaily,
    ResearchFactor,
    ResearchStrategyFactor,
    Run,
    SentimentDaily,
)
from app.national_team_routes import router as national_team_router
from app.research_factor_context import build_external_factor_truth
from app.research_factors import FACTORS, STRATEGIES, calculate_factor_events
from app.research_routes import router as research_router
from app.review_routes import router as review_router
from app.sentiment_routes import router as sentiment_router
from app.strategy_lab import router as strategy_lab_router
from app.strategy_workbench import router as strategy_workbench_router


@asynccontextmanager
async def lifespan(app):
    """随应用启动调度，关闭时停止后续调度检查。"""
    recover_interrupted()
    recover_interrupted(2)
    recover_interrupted(3)
    recover_interrupted(4)
    recover_interrupted(5)
    recover_interrupted(6)
    stop = threading.Event()
    thread = threading.Thread(target=scheduler, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=2)


app = FastAPI(title="ETF Sentinel API", version="0.3.0", lifespan=lifespan)
app.include_router(account_router)
app.include_router(backtest_router)
app.include_router(sentiment_router)
app.include_router(national_team_router)
app.include_router(index_valuation_router)
app.include_router(market_sentiment_router)
app.include_router(research_router)
app.include_router(review_router)
app.include_router(strategy_lab_router)
app.include_router(strategy_workbench_router)


class InstrumentCreate(BaseModel):
    """仅接收 ETF 证券代码。"""

    code: str = Field(pattern=r"^[0-9]{6}$")


class InstrumentUpdate(BaseModel):
    """标的采集开关与回补起点。"""

    enabled: bool
    start_date: date


class JobUpdate(BaseModel):
    """每日北京时间与调度开关。"""

    enabled: bool
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@app.get("/health", tags=["系统"])
def health():
    """仅返回进程存活状态。"""
    return {"status": "ok"}


@app.get("/instruments")
def instruments():
    """返回标的配置及已持久化行情覆盖范围。"""
    with Session() as db:
        result = []
        for item in db.scalars(select(Instrument).order_by(Instrument.code)):
            count, first, last = db.execute(
                select(
                    func.count(), func.min(Candle.date), func.max(Candle.date)
                ).where(Candle.code == item.code)
            ).one()
            result.append(
                {
                    "code": item.code,
                    "name": item.name,
                    "enabled": item.enabled,
                    "start_date": item.start_date,
                    "count": count,
                    "first_date": first,
                    "last_date": last,
                    "source": "ChatBI · daily_ohlcv_etf",
                }
            )
        return result


@app.post("/instruments", status_code=201)
def create_instrument(body: InstrumentCreate):
    """用 ETF 行情源确认代码，登记后启动现有行情任务。"""
    code = body.code
    with Session() as db:
        if db.get(Instrument, code):
            raise HTTPException(409, "该 ETF 已在标的配置中")

    end = now().date() - timedelta(days=1)
    start = end - timedelta(days=29)
    try:
        rows = fetch_rows(code, start, end)
    except ValueError as exc:
        raise HTTPException(502, f"无法确认 ETF 代码：{exc}") from None
    if not rows:
        raise HTTPException(422, "数据源近 30 日未返回该代码的 ETF 行情，请核对代码或稍后重试")
    try:
        latest = max(rows, key=lambda row: validate_row(row, code, start, end)["date"])
    except (ValueError, InvalidOperation):
        raise HTTPException(502, "数据源返回的 ETF 行情未通过校验，请稍后重试") from None

    name = latest.get("STOCK_NAME")
    statement = insert(Instrument).values(code=code)
    if isinstance(name, str) and name.strip():
        statement = statement.values(name=name)
    with Session() as db:
        created = db.scalar(
            statement.on_conflict_do_nothing(index_elements=[Instrument.code]).returning(Instrument.code)
        )
        if created is None:
            raise HTTPException(409, "该 ETF 已在标的配置中")
        db.commit()
    queue_free_backfill(code)
    return {"code": code, "run_id": launch()}


@app.put("/instruments/{code}")
def update_instrument(code: str, body: InstrumentUpdate):
    """更新采集配置，不删除历史行情。"""
    if body.start_date >= now().date():
        raise HTTPException(422, "历史起始日期必须早于今天")
    with Session() as db:
        item = db.get(Instrument, code)
        if not item:
            raise HTTPException(404, "标的尚未配置")
        item.enabled, item.start_date = body.enabled, body.start_date
        db.commit()
    return {"saved": True}


@app.get("/job")
def get_job():
    """返回任务配置、下次执行时间和最近运行记录。"""
    with Session() as db:
        job = db.get(Job, 1)
        runs = db.scalars(
            select(Run).where(Run.job_id == 1).order_by(Run.id.desc()).limit(20)
        ).all()
        return {
            "enabled": job.enabled,
            "time": job.time,
            "next_run": next_run(job),
            "source_configured": True,
            "chatbi_configured": bool(os.getenv("CHATBI_TOKEN")),
            "runs": [
                {
                    "id": r.id,
                    "status": r.status,
                    "trigger": r.trigger,
                    "started_at": r.started_at,
                    "ended_at": r.ended_at,
                    "logs": r.logs,
                }
                for r in runs
            ],
        }


@app.put("/job")
def update_job(body: JobUpdate):
    """持久化任务时间与启停设置。"""
    with Session() as db:
        job = db.get(Job, 1)
        job.enabled, job.time = body.enabled, body.time
        db.commit()
    return {"saved": True}


@app.post("/job/run", status_code=202)
def run_job():
    """手动触发异步采集，优先 ChatBI 并支持静默切换免费源；重复触发返回冲突。"""
    run_id = launch()
    if run_id is None:
        raise HTTPException(409, "采集任务正在运行")
    return {"run_id": run_id}


@app.get("/candles/{code}")
def candles(code: str, start: date, end: date):
    """查询图表用前复权日 K，不触发外部采集。"""
    if start > end or not re.fullmatch(r"\d{6}", code):
        raise HTTPException(422, "代码或日期范围无效")
    with Session() as db:
        if not db.get(Instrument, code):
            raise HTTPException(404, "标的尚未配置")
        rows = db.scalars(
            select(Candle)
            .where(Candle.code == code, Candle.date >= start, Candle.date <= end)
            .order_by(Candle.date)
        ).all()
        raw_rows = [
            {
                "date": r.date,
                "open": str(r.open),
                "high": str(r.high),
                "low": str(r.low),
                "close": str(r.close),
                "adjusted_close": str(r.adjusted_close) if r.adjusted_close is not None else None,
                "volume": float(r.volume),
                "amount": float(r.amount),
                "source_updated_at": r.source_updated_at,
                "collected_at": r.collected_at,
            }
            for r in rows
        ]
        try:
            displayed = front_adjusted_ohlc_rows(raw_rows)
        except ValueError as exc:
            raise HTTPException(422, f"行情复权资料未通过校验：{exc}") from None
        previous_close = None
        result = []
        for row in displayed:
            close = float(row["close"])
            change_pct = (
                (close / previous_close - 1) * 100
                if previous_close is not None else None
            )
            result.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": close,
                "volume": row["volume"],
                "amount": row["amount"],
                "change_pct": change_pct,
                "source_updated_at": row["source_updated_at"],
                "collected_at": row["collected_at"],
            })
            previous_close = close
        return result


@app.get("/factors")
def factor_catalog():
    """返回可观察因子目录及其被哪些策略使用。"""
    with Session() as db:
        factors = list(db.scalars(select(ResearchFactor).order_by(ResearchFactor.category, ResearchFactor.factor_id)))
        relations = list(db.scalars(select(ResearchStrategyFactor).order_by(ResearchStrategyFactor.strategy_id, ResearchStrategyFactor.display_order)))
    by_strategy = {key: [] for key in STRATEGIES}
    by_factor = {row.factor_id: [] for row in factors}
    for relation in relations:
        by_strategy[relation.strategy_id].append({"factor_id": relation.factor_id, "role": relation.role, "display_order": relation.display_order})
        by_factor[relation.factor_id].append(relation.strategy_id)
    return {
        "factors": [
            {"id": row.factor_id, "name": row.factor_name, "category": row.category,
             "output_type": row.output_type, "meaning": row.meaning,
             "chart_visible": row.chart_visible, "strategies": by_factor[row.factor_id]}
            for row in factors
        ],
        "strategies": [
            {"id": key, "name": definition["name"], "description": definition["description"],
             "research_only": definition.get("research_only", False), "factors": by_strategy[key]}
            for key, definition in STRATEGIES.items()
        ],
    }


@app.get("/candles/{code}/factors")
def candle_factors(code: str, start: date, end: date):
    """读取行情图因子标记，按核验行情与权益做因果计算。"""
    if start > end or not re.fullmatch(r"\d{6}", code):
        raise HTTPException(422, "代码或日期范围无效")
    with Session() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if not db.get(Instrument, code):
            raise HTTPException(404, "标的尚未配置")
        latest = db.scalar(
            select(func.max(Candle.date)).where(Candle.code == code, Candle.date <= end)
        )
        if latest is None or latest < start:
            return {"events": [], "data_cutoff": None, "partial": False, "warmup_insufficient": False}
        source = db.get(BacktestSource, code)
        if source is None:
            raise HTTPException(422, "尚无已核验权益资料")
        cutoff = min(latest, source.checked_through_date)
        partial = cutoff < latest
        if cutoff < start:
            return {"events": [], "data_cutoff": None, "partial": partial, "warmup_insufficient": False}
        candles = list(db.scalars(
            select(Candle)
            .where(Candle.code == code, Candle.date <= cutoff)
            .order_by(Candle.date)
        ))
        rows = [
            {
                "trade_date": str(row.date),
                **{
                    key: str(getattr(row, key)) if getattr(row, key) is not None else None
                    for key in ("open", "high", "low", "close", "adjusted_close", "volume")
                },
            }
            for row in candles
        ]
        try:
            validate_market(rows, source.corporate_actions, allow_splits=True)
            indicator_rows = indicator_ohlc_rows(rows, source.corporate_actions)
        except ValueError as exc:
            raise HTTPException(422, f"行情或权益资料未通过校验：{exc}") from None
        index_codes = list(
            db.scalars(
                select(InstrumentIndexLink.index_code)
                .where(InstrumentIndexLink.instrument_code == code)
                .order_by(InstrumentIndexLink.index_code)
            )
        )
        valuation_rows = [
            {
                "trade_date": str(item.trade_date),
                "metric_key": item.metric_key,
                "metric_value": str(item.metric_value),
                "value_status": item.value_status,
            }
            for item in db.scalars(
                select(IndexValuationDaily)
                .where(
                    IndexValuationDaily.index_code.in_(index_codes),
                    IndexValuationDaily.trade_date <= cutoff,
                )
                .order_by(IndexValuationDaily.trade_date, IndexValuationDaily.metric_key)
            )
        ]
        benchmark_rows = [
            {
                "trade_date": str(item.trade_date),
                "close": str(item.close_price),
            }
            for item in db.scalars(
                select(IndexCandle)
                .where(
                    IndexCandle.index_code == "000300.SH",
                    IndexCandle.trade_date <= cutoff,
                )
                .order_by(IndexCandle.trade_date)
            )
        ]
        sentiment_links = list(
            db.scalars(
                select(InstrumentSentimentLink)
                .where(InstrumentSentimentLink.instrument_code == code)
                .order_by(InstrumentSentimentLink.category_key)
            )
        )
        sentiment_rows = None
        if len(sentiment_links) == 1:
            sentiment_rows = [
                {
                    "trade_date": str(item.trade_date),
                    "fear_greed_score": str(item.fear_greed_score),
                }
                for item in db.scalars(
                    select(SentimentDaily)
                    .where(
                        SentimentDaily.category_key == sentiment_links[0].category_key,
                        SentimentDaily.trade_date <= cutoff,
                    )
                    .order_by(SentimentDaily.trade_date)
                )
            ]
        market_rows = [
            {
                "trade_date": str(item.trade_date),
                "fear_greed_score": str(item.fear_greed_score),
            }
            for item in db.scalars(
                select(MarketFearGreedDaily)
                .where(MarketFearGreedDaily.trade_date <= cutoff)
                .order_by(MarketFearGreedDaily.trade_date)
            )
        ]
        market_regime_rows = [
            {
                "factor_key": item.factor_key,
                "trade_date": str(item.trade_date),
                "raw_value": str(item.raw_value),
            }
            for item in db.scalars(
                select(MarketRegimeFactorDaily)
                .where(MarketRegimeFactorDaily.trade_date <= cutoff)
                .order_by(
                    MarketRegimeFactorDaily.factor_key,
                    MarketRegimeFactorDaily.trade_date,
                )
            )
        ]

    turning = turning_events(
        indicator_rows,
        [],
        turning_profile(code)["parameters"],
    )
    # 指标行情已包含权益调整，不再次把现金分红加入收盘价。
    external_truth, external_coverage = build_external_factor_truth(
        indicator_rows,
        valuation_rows=valuation_rows,
        sentiment_rows=sentiment_rows,
        market_rows=market_rows,
        market_regime_rows=market_regime_rows,
    )
    events = calculate_factor_events(
        indicator_rows,
        turning,
        external_truth=external_truth,
        benchmark_rows=benchmark_rows,
    )
    return {
        "events": [
            {**event, **FACTORS[event["factor_id"]]}
            for event in events
            if event["trade_date"] >= start.isoformat()
        ],
        "data_cutoff": rows[-1]["trade_date"],
        "partial": partial,
        "warmup_insufficient": sum(row["trade_date"] <= start.isoformat() for row in rows) < SHARED_WARMUP_BARS,
        "external_factor_context": {
            "valuation_index_codes": index_codes,
            "sentiment_category_keys": [item.category_key for item in sentiment_links],
            "coverage": external_coverage,
            "benchmark": {
                "available": bool(benchmark_rows),
                "index_code": "000300.SH",
                "first_source_date": benchmark_rows[0]["trade_date"]
                if benchmark_rows
                else None,
                "last_source_date": benchmark_rows[-1]["trade_date"]
                if benchmark_rows
                else None,
                "reason": None
                if benchmark_rows
                else "本地缺少沪深300指数日K，相关强弱因子不可用",
            },
        },
    }
