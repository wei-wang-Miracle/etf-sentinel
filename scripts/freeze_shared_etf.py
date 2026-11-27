"""从本地已核验行情冻结共享 ETF 固定先验研究输入。"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def digest(path):
    """返回文件内容的 SHA-256 摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    """以可审查的 UTF-8 JSON 写入新的冻结文件。"""
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

    from app.db import Session, engine
    from app.models import BacktestSource, Candle, Instrument, InstrumentIndexLink
    from app.shared_etf_snapshot import (
        SNAPSHOT_CODES,
        build_snapshot_item,
        role_for_code,
    )

    if engine.url.host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("共享ETF研究冻结只允许读取本地数据库")

    universe, coverage = {}, {}
    with Session() as db:
        for code in SNAPSHOT_CODES:
            instrument = db.get(Instrument, code)
            source = db.get(BacktestSource, code)
            candles = list(
                db.scalars(
                    select(Candle).where(Candle.code == code).order_by(Candle.date)
                )
            )
            if instrument is None or source is None or not candles:
                raise ValueError(f"{code}缺少本地行情或已核验权益资料")
            if source.checked_through_date < candles[-1].date:
                raise ValueError(f"{code}权益资料未核验至行情截止日")
            indices = list(
                db.scalars(
                    select(InstrumentIndexLink.index_code)
                    .where(InstrumentIndexLink.instrument_code == code)
                    .order_by(InstrumentIndexLink.index_code)
                )
            )
            role = role_for_code(code)
            if role == "core" and len(indices) != 1:
                raise ValueError(f"{code}缺少唯一关联指数，无法作为宽基代表候选")
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
            item, item_coverage = build_snapshot_item(
                code=code,
                name=instrument.name,
                rows=rows,
                actions=source.corporate_actions,
                indices=indices,
                role=role,
                source={
                    "market_source": "本地已核验ETF日行情",
                    "market_first_collected_at": candles[0].collected_at.isoformat(),
                    "market_last_collected_at": candles[-1].collected_at.isoformat(),
                    "equity_source_url": source.source_url,
                    "equity_source_sha256": source.source_sha256,
                    "equity_checked_through_date": str(source.checked_through_date),
                    "equity_collected_at": source.collected_at.isoformat(),
                },
            )
            universe[code] = item
            coverage[code] = item_coverage

    directory.mkdir(parents=True)
    input_path = directory / "input.json"
    write(input_path, universe)
    sources = {
        str(path.relative_to(ROOT)): digest(path)
        for path in (
            ROOT / "scripts/freeze_shared_etf.py",
            ROOT / "api/app/shared_etf_snapshot.py",
        )
    }
    write(
        directory / "manifest.json",
        {
            "version": "shared-etf-external-snapshot-v1.0.0",
            "created_at": datetime.now(UTC).isoformat(),
            "input_sha256": digest(input_path),
            "end": min(item["end"] for item in coverage.values()),
            "coverage": coverage,
            "sources": sources,
            "evidence": (
                "从本地已核验行情与权益资料生成；当前本地覆盖不足2019年，"
                "不构成长周期或真正未见验证"
            ),
            "accounting": (
                "历史OHLC、成交量和每份现金分红已按份额折算转换到冻结末日"
                "的统一份额口径；原始折算事件只保留在coverage摘要"
            ),
        },
    )
    print(
        f"已冻结 {len(universe)} 只ETF，覆盖至"
        f" {min(item['end'] for item in coverage.values())}；未发布策略。"
    )


if __name__ == "__main__":
    main()
