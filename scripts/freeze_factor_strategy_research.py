"""从本地已核验行情冻结分类因子策略研究输入（默认 2019-01-01 起）。"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

MIN_ROWS = 67
MIN_SUSPENSION_AUDIT_SOURCES = 3


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _verified_suspensions_for(code, report_data, actual_days):
    """只放行三方报告逐日确认均无成交的真实停牌日。"""
    from app.backtest_data import trading_days

    if not actual_days:
        return ()
    expected, _ = trading_days(actual_days[0], actual_days[-1])
    missing = sorted(set(expected) - set(actual_days))
    if not missing:
        return ()
    if not report_data:
        raise ValueError(f"{code} 存在缺失交易日 {missing}，且缺少免费源对比报告可供核验")

    item = (report_data.get("items") or {}).get(code)
    if not item or item.get("status") != "ok":
        raise ValueError(f"{code} 未通过免费源验证报告，不能放行停牌日 {missing}")

    audit = (item.get("cross_check") or {}).get("suspension_audit") or {}
    source_count = audit.get("available_source_count")
    if not isinstance(source_count, int) or source_count < MIN_SUSPENSION_AUDIT_SOURCES:
        raise ValueError(
            f"{code} 停牌审计可用源不足三方，不能放行停牌日 {missing}"
        )
    verified = {
        record.get("trade_date")
        for record in audit.get("verified_suspensions") or []
        if isinstance(record, dict)
        and isinstance(record.get("trade_date"), str)
        and len(record.get("sources") or []) >= MIN_SUSPENSION_AUDIT_SOURCES
    }
    unverified = [day for day in missing if day not in verified]
    if unverified:
        raise ValueError(f"{code} 缺失交易日 {unverified} 未经三方逐日审计确认，拒绝放行")
    return tuple(missing)


def research_window_dates(start_date, end_date):
    """将命令行窗口解析为数据库日期，拒绝倒置区间。"""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else None
    if end is not None and end < start:
        raise ValueError("研究截止日期不能早于起始日期")
    return start, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="必须不存在的新冻结目录")
    parser.add_argument(
        "--start-date",
        default="2019-01-01",
        help="研究样本起始日期 YYYY-MM-DD（默认 2019-01-01）",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="研究样本截止日期 YYYY-MM-DD；默认读取本地已核验行情的最新日期",
    )
    parser.add_argument(
        "--verification-report",
        type=Path,
        default=ROOT / ".local" / "free-history-verification.json",
        help="免费历史行情跨源核验报告路径，用于放行真实停牌日",
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        parser.error("冻结目录已存在，不能覆盖")
    try:
        research_start_date, research_end_date = research_window_dates(
            args.start_date, args.end_date
        )
    except ValueError as exc:
        parser.error(str(exc))

    report_data = (
        json.loads(args.verification_report.read_text())
        if args.verification_report.is_file()
        else None
    )

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from sqlalchemy import select

    from app.algorithm_templates import turning_events, turning_profile
    from app.db import Session, engine
    from app.factor_strategy_snapshot import build_factor_snapshot_item
    from app.models import (
        BacktestSource,
        Candle,
        IndexValuationDaily,
        Instrument,
        InstrumentIndexLink,
        InstrumentSentimentLink,
        SentimentDaily,
    )

    if engine.url.host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("分类因子策略研究冻结只允许读取本地数据库")

    universe, coverage, excluded = {}, {}, {}
    with Session() as db:
        instruments = list(db.scalars(select(Instrument).order_by(Instrument.code)))
        for instrument in instruments:
            code = instrument.code
            source = db.get(BacktestSource, code)
            candles = list(
                db.scalars(
                    select(Candle)
                    .where(
                        Candle.code == code,
                        Candle.date >= research_start_date,
                        *([Candle.date <= research_end_date] if research_end_date else []),
                    )
                    .order_by(Candle.date)
                )
            )
            if source is None or not candles:
                excluded[code] = "缺少本地行情或已核验权益资料"
                continue
            if source.checked_through_date < candles[-1].date:
                excluded[code] = "权益资料未核验至行情截止日"
                continue
            if len(candles) < MIN_ROWS:
                excluded[code] = f"有效日行情不足{MIN_ROWS}根，无法覆盖统一预热与首个次日执行"
                continue
            indices = list(
                db.scalars(
                    select(InstrumentIndexLink.index_code)
                    .where(InstrumentIndexLink.instrument_code == code)
                    .order_by(InstrumentIndexLink.index_code)
                )
            )
            rows = [
                {
                    "trade_date": str(candle.date),
                    "open": str(candle.open),
                    "high": str(candle.high),
                    "low": str(candle.low),
                    "close": str(candle.close),
                    "volume": str(candle.volume),
                    "amount": str(candle.amount),
                }
                for candle in candles
            ]
            actual_days = [row["trade_date"] for row in rows]
            suspensions = _verified_suspensions_for(code, report_data, actual_days)
            actions = source.corporate_actions
            valuation_index_codes = indices if len(indices) == 1 else []
            valuation_rows = [
                {
                    "trade_date": str(item.trade_date),
                    "metric_key": item.metric_key,
                    "metric_value": str(item.metric_value),
                    "value_status": item.value_status,
                    "collected_at": item.collected_at.isoformat(),
                }
                for item in db.scalars(
                    select(IndexValuationDaily)
                    .where(
                        IndexValuationDaily.index_code.in_(valuation_index_codes),
                        IndexValuationDaily.trade_date <= candles[-1].date,
                    )
                    .order_by(IndexValuationDaily.trade_date, IndexValuationDaily.metric_key)
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
                        "collected_at": item.collected_at.isoformat(),
                    }
                    for item in db.scalars(
                        select(SentimentDaily)
                        .where(
                            SentimentDaily.category_key == sentiment_links[0].category_key,
                            SentimentDaily.trade_date <= candles[-1].date,
                        )
                        .order_by(SentimentDaily.trade_date)
                    )
                ]
            turning = turning_events(
                rows,
                [
                    event
                    for event in actions.get("dividends", [])
                    if event["ex_date"] >= actual_days[0]
                ],
                turning_profile(code)["parameters"],
            )
            item, item_coverage = build_factor_snapshot_item(
                code=code,
                name=instrument.name,
                rows=rows,
                actions=actions,
                indices=indices,
                source={
                    "market_source": "本地已核验ETF日行情",
                    "market_first_collected_at": candles[0].collected_at.isoformat(),
                    "market_last_collected_at": candles[-1].collected_at.isoformat(),
                    "equity_source_url": source.source_url,
                    "equity_source_sha256": source.source_sha256,
                    "equity_checked_through_date": str(source.checked_through_date),
                    "equity_collected_at": source.collected_at.isoformat(),
                },
                turning=turning,
                start_date=args.start_date,
                verified_suspensions=suspensions,
                factor_context={
                    "valuation_index_codes": valuation_index_codes,
                    "valuation_rows": valuation_rows,
                    "sentiment_category_keys": [
                        item.category_key for item in sentiment_links
                    ],
                    "sentiment_rows": sentiment_rows,
                },
            )
            universe[code] = item
            coverage[code] = item_coverage

    if not universe:
        raise ValueError("没有满足研究数据要求的ETF")
    directory.mkdir(parents=True)
    input_path = directory / "input.json"
    write(
        input_path,
        {
            "version": "factor-strategy-snapshot-v1.2.0",
            "start_date": args.start_date,
            "universe": universe,
            "excluded": excluded,
        },
    )
    sources = {
        str(path.relative_to(ROOT)): digest(path)
        for path in (
            ROOT / "scripts/freeze_factor_strategy_research.py",
            ROOT / "api/app/factor_strategy_snapshot.py",
            ROOT / "api/app/research_factors.py",
            ROOT / "api/app/research_factor_context.py",
            ROOT / "api/app/algorithm_templates.py",
            ROOT / "api/app/free_market_sources.py",
        )
    }
    write(
        directory / "manifest.json",
        {
            "version": "factor-strategy-snapshot-v1.2.0",
            "created_at": datetime.now(UTC).isoformat(),
            "start_date": args.start_date,
            "input_sha256": digest(input_path),
            "instrument_count": len(universe),
            "excluded": excluded,
            "end": min(item["end"] for item in coverage.values()),
            "coverage": coverage,
            "sources": sources,
            "evidence": (
                f"冻结内容来自本地已核验ETF日行情（{args.start_date}起）、权益资料与指数映射，"
                "经多源核验的真实停牌日明确登记在coverage；研究结果不构成未来有效性证明。"
            ),
            "accounting": (
                "历史OHLC、成交量和每份现金分红已按份额折算转换到冻结末日的统一份额口径；"
                "原始折算事件只保留在coverage摘要。"
            ),
        },
    )
    print(
        f"已冻结 {len(universe)} 只ETF（起点 {args.start_date}），排除 {len(excluded)} 只，"
        f"覆盖至 {min(item['end'] for item in coverage.values())}；未发布策略。"
    )


if __name__ == "__main__":
    main()
