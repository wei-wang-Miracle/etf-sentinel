"""从本地已核验行情冻结分类因子策略研究输入（默认 2019-01-01 起）。"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

MIN_ROWS = 67


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _verified_suspensions_for(code, report_data, actual_days):
    """基于三源对比审计报告核验缺失日是否确为全网一致无交易的停牌日。"""
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

    cross = item.get("cross_check") or {}
    peers = cross.get("peers") or {}
    if not peers:
        raise ValueError(f"{code} 缺少可用横向对照源，不能放行停牌日 {missing}")

    peer_present_missing = {
        day
        for peer_info in peers.values()
        for day in (peer_info.get("primary_missing_dates") or [])
    }
    unverified = [day for day in missing if day in peer_present_missing]
    if unverified:
        raise ValueError(f"{code} 缺失交易日 {unverified} 在其他可用源有交易记录，拒绝放行")
    return tuple(missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="必须不存在的新冻结目录")
    parser.add_argument(
        "--start-date",
        default="2019-01-01",
        help="研究样本起始日期 YYYY-MM-DD（默认 2019-01-01）",
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
    from app.models import BacktestSource, Candle, Instrument, InstrumentIndexLink

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
                    .where(Candle.code == code, Candle.date >= args.start_date)
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
            "version": "factor-strategy-snapshot-v1.1.0",
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
            ROOT / "api/app/algorithm_templates.py",
        )
    }
    write(
        directory / "manifest.json",
        {
            "version": "factor-strategy-snapshot-v1.1.0",
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
