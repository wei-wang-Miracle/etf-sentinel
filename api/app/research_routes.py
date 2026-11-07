"""投研对象和横向比较的本地数据查询。"""

from datetime import date

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.account_state import latest_holdings
from app.backtest_data import trading_days
from app.db import Session
from app.models import (
    BacktestSource,
    Candle,
    Instrument,
    InstrumentIndexLink,
)
from app.research_compare import compare_prices

router = APIRouter(prefix="/research", tags=["投研分析"])


def _universe(db):
    """读取最新账户快照中的正持仓；旧快照和零数量不构成当前研究集合。"""
    latest, rows = latest_holdings(db)
    held = {row.instrument_code for row in rows if row.current_amount > 0}
    instruments = list(db.scalars(select(Instrument).order_by(Instrument.code)))
    held.intersection_update(item.code for item in instruments)
    return instruments, held, latest


@router.get("/universe")
def research_universe():
    """ETF 是唯一研究主体，默认优先最新正持仓，同时保留全部配置入口。"""
    with Session() as db:
        instruments, held, latest = _universe(db)
        ordered = sorted(
            instruments, key=lambda item: (item.code not in held, item.code)
        )
        return {
            "items": [
                {
                    "type": "etf",
                    "code": item.code,
                    "name": item.name,
                    "held": item.code in held,
                }
                for item in ordered
            ],
            "held_codes": sorted(held),
            "holdings_as_of": latest,
            "default_code": ordered[0].code if ordered else None,
        }


@router.get("/compare/prices")
def compare_etf_prices(start: date, end: date):
    """按共同交易日比较配置内 ETF 原始价格。"""
    if start > end:
        raise HTTPException(422, "起始日期不能晚于截止日期")
    try:
        calendar, _ = trading_days(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    days = [date.fromisoformat(day) for day in calendar]
    if not days:
        raise HTTPException(422, "所选区间没有交易日")
    with Session() as db:
        instruments = db.scalars(select(Instrument).order_by(Instrument.code)).all()
        rows = db.scalars(
            select(Candle)
            .where(Candle.date >= days[0], Candle.date <= days[-1])
            .order_by(Candle.date)
        ).all()
        sources = {
            source.instrument_code: source
            for source in db.scalars(select(BacktestSource))
        }
        series = {item.code: [] for item in instruments}
        for row in rows:
            if row.code in series:
                series[row.code].append((row.date, row.close))
        compared = compare_prices(series, days)
        items = []
        for item in instruments:
            result = compared[item.code]
            source = sources.get(item.code)
            if source and any(
                str(days[0]) <= split["effective_date"] <= str(days[-1])
                for split in source.corporate_actions.get("splits", [])
            ):
                result = {"status": "split", "change_pct": None, "points": []}
            items.append({"code": item.code, "name": item.name, **result})
    return {
        "start": days[0],
        "end": days[-1],
        "dates": days,
        "items": items,
        "description": "原始收盘价格变化，复权口径未确认，不含分红；未核验的拆分可能影响比较。",
    }


@router.get("/compare")
def comparison(
    dimension: str,
    start: date,
    end: date,
    metric: str = "pe",
    codes: str | None = None,
    scope: str = "held",
):
    """统一横截面与序列，同一排名使用共同评价日，缺失不补零。"""
    from app.index_valuation import METRICS
    from app.index_valuation_routes import metric_rows
    from app.models import (
        NationalTeamDaily,
        ResearchIndex,
        SentimentCategory,
        SentimentDaily,
    )
    from app.research_compare import compare_observations, trend_statistics

    if (
        start > end
        or dimension not in ("valuation", "sentiment", "holdings", "trend", "factors")
        or metric not in METRICS
        or scope not in ("held", "all")
    ):
        raise HTTPException(422, "比较维度、指标或日期无效")
    chosen = codes.split(",") if codes else None
    if chosen is not None and len(chosen) > 6:
        raise HTTPException(422, "图表最多选择六个对象")
    try:
        calendar, version = trading_days(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if not calendar:
        raise HTTPException(422, "所选区间没有交易日")
    days = [date.fromisoformat(d) for d in calendar]
    if dimension == "factors":
        return {
            "dimension": dimension,
            "as_of": days[-1],
            "start": days[0],
            "end": days[-1],
            "items": [],
            "series": [],
            "universe": {"total": 20, "covered": 0},
            "heatmap": None,
            "warnings": ["因子能力尚未接入；不虚构评分和权重"],
            "meta": {
                "unit": "支持分",
                "source": "尚未接入",
                "calculation": "后续统一因子接口",
            },
        }
    with Session() as db:
        instruments, held, holdings_as_of = _universe(db)
        instruments = [
            item for item in instruments if scope == "all" or item.code in held
        ]
        names, values, labels, heatmap = {}, {}, {}, None
        index_links, index_names, shared = {}, {}, {}
        if dimension == "valuation":
            index_links = {
                link.instrument_code: link.index_code
                for link in db.scalars(select(InstrumentIndexLink))
            }
            index_names = {
                row.index_code: row.index_name
                for row in db.scalars(select(ResearchIndex))
            }
            for item in instruments:
                if index_links.get(item.code):
                    shared.setdefault(index_links[item.code], []).append(item.code)
            cache, matrix = {}, []
            for item in instruments:
                names[item.code] = item.name
                index_code = index_links.get(item.code)
                matrix_row = []
                for key in METRICS:
                    if (index_code, key) not in cache:
                        rows, ranks = (
                            metric_rows(db, index_code, key) if index_code else ([], [])
                        )
                        cache[index_code, key] = [
                            (r.trade_date, rank if r.value_status == "valid" else None)
                            for r, rank in zip(rows, ranks, strict=True)
                            if r.trade_date <= days[-1]
                        ]
                    points = cache[index_code, key]
                    if key == metric:
                        values[item.code] = points
                    matrix_row.append(dict(points).get(days[-1]))
                matrix.append(matrix_row)
            heatmap = {
                "rows": [f"{code} · {name}" for code, name in names.items()],
                "columns": [v[0] for v in METRICS.values()],
                "values": matrix,
            }
            unit, source = (
                "本地分位（%）",
                "ETF关联指数 · 韭圈估值；本地十日历年因果窗口",
            )
            note = "ETF估值来自关联指数；共享同一指数的ETF数值相同，不构成独立证据或ETF优劣排名。只比较截至当日的本地分位；来源当前分位不回填历史，源历史可能修订，不代表原时点已知；股息率及ROE不自动解释为高低估。"
        elif dimension == "sentiment":
            for category in db.scalars(
                select(SentimentCategory).order_by(SentimentCategory.category_key)
            ):
                code = category.category_key
                names[code] = category.category_name
                rows = list(
                    db.scalars(
                        select(SentimentDaily)
                        .where(
                            SentimentDaily.category_key == code,
                            SentimentDaily.trade_date >= days[0],
                            SentimentDaily.trade_date <= days[-1],
                        )
                        .order_by(SentimentDaily.trade_date)
                    )
                )
                values[code] = [(r.trade_date, r.fear_greed_score) for r in rows]
                labels[code] = (
                    category.snapshot_label
                    if rows
                    and category.snapshot_date == rows[-1].trade_date
                    and category.snapshot_score == rows[-1].fear_greed_score
                    else None
                )
            unit, source = "恐贪分数", "韭圈行业恐贪"
            note = "类别自身情绪，不映射为宽基ETF情绪；标签只使用同日同分数源标签，不推断阈值。"
        elif dimension == "holdings":
            for item in instruments:
                names[item.code] = item.name
                values[item.code] = [
                    (r.trade_date, r.estimated_holding_pct)
                    for r in db.scalars(
                        select(NationalTeamDaily)
                        .where(
                            NationalTeamDaily.instrument_code == item.code,
                            NationalTeamDaily.trade_date >= days[0],
                            NationalTeamDaily.trade_date <= days[-1],
                        )
                        .order_by(NationalTeamDaily.trade_date)
                    )
                ]
            unit, source = "估算持仓比例（%）", "韭圈国家队ETF；固定2026-01-01基准"
            note = "比例为估算，不是真实账户持仓，也不代表看好程度；变化须同起止源日期，端点缺失不比较变化。"
        else:
            for item in instruments:
                names[item.code] = item.name
                values[item.code] = [
                    (r.date, r.close)
                    for r in db.scalars(
                        select(Candle)
                        .where(Candle.code == item.code, Candle.date <= days[-1])
                        .order_by(Candle.date)
                    )
                ]
            unit, source = "价格指数（起点100）", "财通证券本地原始收盘"
            note = "复权口径未确认，不含分红，不是总收益；已知拆分对象不参与比较。"
        compared = (
            compare_observations(values, days)
            if dimension != "trend"
            else {
                code: trend_statistics(points, days) for code, points in values.items()
            }
        )
        items = []
        for code, name in names.items():
            value = compared[code]
            if dimension == "trend":
                source_row = db.get(BacktestSource, code)
                splits = (
                    source_row.corporate_actions.get("splits", []) if source_row else []
                )
                if any(
                    str(days[0]) <= event["effective_date"] <= str(days[-1])
                    for event in splits
                ):
                    value.update(status="split", change_pct=None, points=[])
                value["latest"] = value.get("change_pct")
                value["change"] = value.get("change_pct")
                if not source_row or source_row.checked_through_date < days[-1]:
                    value["warning"] = "拆分权益未完整核验，原始价格统计仅供参考"
            items.append(
                dict(
                    code=code,
                    name=name,
                    object_type="sentiment" if dimension == "sentiment" else "etf",
                    **value,
                    source_label=labels.get(code),
                    index_code=index_links.get(code),
                    index_name=index_names.get(index_links.get(code)),
                    shared_index_codes=shared.get(index_links.get(code), []),
                )
            )
        items.sort(
            key=lambda item: (
                item["status"] == "available",
                item.get("latest") if item.get("latest") is not None else float("-inf"),
            ),
            reverse=True,
        )
        ranking = 0
        ranks = {}
        for item in items:
            if item["status"] == "available" and item.get("latest") is not None:
                ranking += 1
                ranks.setdefault(item["latest"], ranking)
                item["rank"] = ranks[item["latest"]]
            else:
                item["rank"] = None
        selected = (
            chosen
            if chosen is not None
            else [item["code"] for item in items if item["rank"]][:6]
        )
        warnings = [note]
        if dimension != "sentiment":
            warnings.append(
                f"集合依据最新真实持仓快照：{holdings_as_of or '未同步'}；当前持仓回看历史属于事后选择样本。"
            )
            if scope == "held" and not held:
                warnings.append(
                    "暂无最新正持仓ETF，请同步账户或切换全部配置；不自动替换研究集合。"
                )
        if chosen and any(code not in names for code in chosen):
            warnings.append("已忽略不属于当前维度的代码")
        series = []
        for item in items:
            if item["code"] in selected:
                points = item.pop("points")
                if dimension == "trend":
                    points = (
                        list(zip(calendar, points, strict=True))
                        if points and item["status"] == "available"
                        else []
                    )
                series.append(
                    {
                        "code": item["code"],
                        "name": f"{item['code']} · {item['name']}",
                        "index_code": item["index_code"],
                        "points": points,
                        "drawdowns": list(zip(calendar, item.get("drawdowns", [])))
                        if item["status"] == "available"
                        else [],
                    }
                )
            item.pop("points", None)
            item.pop("drawdowns", None)
        if dimension == "sentiment":
            heatmap = {
                "rows": list(names.values()),
                "columns": calendar,
                "values": [
                    [dict(values[code]).get(day) for day in days] for code in names
                ],
            }
        return {
            "dimension": dimension,
            "as_of": days[-1],
            "start": days[0],
            "end": days[-1],
            "universe": {
                "total": len(items),
                "covered": ranking,
                "scope": "market" if dimension == "sentiment" else scope,
                "holdings_as_of": holdings_as_of,
                "independent_sources": len(shared)
                if dimension == "valuation"
                else None,
            },
            "items": items,
            "series": series,
            "heatmap": heatmap,
            "warnings": warnings,
            "meta": {
                "unit": unit,
                "source": source,
                "calculation": note,
                "calendar_version": version,
                "annualization_factor": 252,
                "stale_rule": "共同评价日无有效观测则不参与排名；不前向填充，缺失不补零",
            },
        }


@router.get("/object")
def research_object(object_type: str, code: str):
    """以可交易ETF汇总摘要；旧指数请求映射至关联ETF，并保留来源提示。"""
    from app.account_routes import holdings
    from app.index_valuation_routes import overview
    from app.models import (
        AccountEntrust,
        InstrumentIndexLink,
        NationalTeamDaily,
        NationalTeamInstrument,
    )
    from app.sentiment_routes import categories

    if object_type not in ("etf", "index"):
        raise HTTPException(422, "研究对象类型无效")
    redirected_from = None
    with Session() as db:
        if object_type == "index":
            instruments, held, _ = _universe(db)
            linked_codes = set(
                db.scalars(
                    select(InstrumentIndexLink.instrument_code).where(
                        InstrumentIndexLink.index_code == code
                    )
                )
            )
            candidates = sorted(
                (item.code for item in instruments if item.code in linked_codes),
                key=lambda candidate: (candidate not in held, candidate),
            )
            if not candidates:
                raise HTTPException(
                    404, "该指数没有关联的配置内ETF，不能作为独立研究对象"
                )
            redirected_from = {"type": "index", "code": code}
            object_type, code = "etf", candidates[0]
        item = db.get(Instrument, code)
        if not item:
            raise HTTPException(404, "ETF不在当前配置范围内")
        links = list(
            db.scalars(
                select(InstrumentIndexLink).where(
                    InstrumentIndexLink.instrument_code == code
                )
            )
        )
        index_code = links[0].index_code if links else None
        latest_prices = list(
            db.scalars(
                select(Candle)
                .where(Candle.code == code)
                .order_by(Candle.date.desc())
                .limit(2)
            )
        )
        price_summary = {
            "value": latest_prices[0].close if latest_prices else None,
            "as_of": latest_prices[0].date if latest_prices else None,
            "change_pct": float(
                (latest_prices[0].close / latest_prices[1].close - 1) * 100
            )
            if len(latest_prices) == 2 and latest_prices[1].close > 0
            else None,
        }
        valuations = next(
            (r for r in overview()["indices"] if r["index_code"] == index_code), None
        )
        linked = []
        for link in links:
            nation_row = db.scalar(
                select(NationalTeamDaily)
                .where(NationalTeamDaily.instrument_code == link.instrument_code)
                .order_by(NationalTeamDaily.trade_date.desc())
                .limit(1)
            )
            linked.append(
                {
                    "code": link.instrument_code,
                    "name": db.get(Instrument, link.instrument_code).name,
                    "national_team_ratio": nation_row.estimated_holding_pct
                    if nation_row
                    else None,
                    "national_team_as_of": nation_row.trade_date
                    if nation_row
                    else None,
                }
            )
        holding_data = holdings()
        holding = (
            next(
                (
                    h
                    for h in holding_data["items"]
                    if h["instrument_code"] == code and h["current_amount"] > 0
                ),
                None,
            )
            if holding_data
            else None
        )
        count = db.scalar(
            select(func.count())
            .select_from(AccountEntrust)
            .where(
                AccountEntrust.instrument_code == code,
                AccountEntrust.account_id == 1,
                AccountEntrust.business_amount > 0,
            )
        )
        nation = db.get(NationalTeamInstrument, code)
        latest = (
            db.scalar(
                select(NationalTeamDaily)
                .where(NationalTeamDaily.instrument_code == code)
                .order_by(NationalTeamDaily.trade_date.desc())
                .limit(1)
            )
            if nation
            else None
        )
        candidates = [code]
        eligibility = []
        for candidate in candidates:
            source = db.get(BacktestSource, candidate)
            last = db.scalar(
                select(Candle)
                .where(Candle.code == candidate)
                .order_by(Candle.date.desc())
                .limit(1)
            )
            eligibility.append(
                {
                    "code": candidate,
                    "status": "available"
                    if source and last and source.checked_through_date >= last.date
                    else "needs_validation",
                    "reason": "具体区间仍须通过日历、预热与权益校验"
                    if source and last and source.checked_through_date >= last.date
                    else "需要行情或更新权益核验",
                }
            )
        return {
            "object": {
                "type": object_type,
                "code": code,
                "name": item.name,
            },
            "redirected_from": redirected_from,
            "linked": {
                "index_code": index_code,
                "instruments": linked,
                "national_team_tracked": bool(nation),
            },
            "summary": {
                "price": price_summary,
                "valuation": valuations,
                "holding": holding,
                "investment_status": "not_synced"
                if holding_data and holding_data["as_of"] is None
                else "holding"
                if holding
                else "closed"
                if count
                else "not_traded",
                "holdings_as_of": holding_data["as_of"] if holding_data else None,
                "trade_count": count,
                "national_team": {
                    "ratio": latest.estimated_holding_pct if latest else None,
                    "as_of": latest.trade_date if latest else None,
                },
                "sentiment": categories(),
                "factors": {"status": "not_implemented"},
            },
            "eligibility": eligibility,
            "warnings": (
                [
                    "旧指数链接已映射至关联ETF；指数仅提供因子来源，可在ETF列表切换其他关联标的。"
                ]
                if redirected_from
                else []
            )
            + [
                "行业恐贪仅作市场背景，未建立直接映射",
                "当前快照不是历史时点持仓；国家队比例不代表个人持仓",
            ],
        }
