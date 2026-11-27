"""从本地已核验行情冻结分类因子策略研究输入。"""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="必须不存在的新冻结目录")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory.exists():
        parser.error("冻结目录已存在，不能覆盖")

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
                    select(Candle).where(Candle.code == code).order_by(Candle.date)
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
            actions = source.corporate_actions
            turning = turning_events(
                rows, actions.get("dividends", []), turning_profile(code)["parameters"]
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
            "version": "factor-strategy-snapshot-v1.0.0",
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
            "version": "factor-strategy-snapshot-v1.0.0",
            "created_at": datetime.now(UTC).isoformat(),
            "input_sha256": digest(input_path),
            "instrument_count": len(universe),
            "excluded": excluded,
            "end": min(item["end"] for item in coverage.values()),
            "coverage": coverage,
            "sources": sources,
            "evidence": (
                "冻结内容来自本地已核验ETF日行情、权益资料与指数映射；"
                "当前历史长度有限，研究结果不构成未来有效性证明。"
            ),
            "accounting": (
                "历史OHLC、成交量和每份现金分红已按份额折算转换到冻结末日的统一份额口径；"
                "原始折算事件只保留在coverage摘要。"
            ),
        },
    )
    print(
        f"已冻结 {len(universe)} 只ETF，排除 {len(excluded)} 只，"
        f"覆盖至 {min(item['end'] for item in coverage.values())}；未发布策略。"
    )


if __name__ == "__main__":
    main()
