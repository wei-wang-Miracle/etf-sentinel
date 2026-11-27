"""验证并回补配置内 ETF 自上市以来的免费历史日行情。"""

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="确认对比验证全部通过后将缺失历史行写入本地数据库；不传时只做验证",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="可选最大源交易日 YYYY-MM-DD；默认使用各标的当前最新库内日期或安全收盘日",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".local" / "free-history-verification.json",
        help="验证与回补审计报告输出路径",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    from app.collection import now
    from app.db import Session, engine
    from app.free_market_sources import (
        backfill_instrument_history,
        free_backfill_end_date,
    )
    from app.models import Candle, Instrument

    if args.apply and engine.url.host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("历史行情回补只允许写入本地 PostgreSQL 数据库")

    explicit_end = date.fromisoformat(args.end_date) if args.end_date else None
    report_items = {}
    failures = []

    with Session() as db:
        instruments = list(db.scalars(select(Instrument).order_by(Instrument.code)))
        for instrument in instruments:
            code = instrument.code
            latest_local = db.scalar(
                select(Candle.date)
                .where(Candle.code == code)
                .order_by(Candle.date.desc())
                .limit(1)
            )
            target_end = explicit_end or latest_local or free_backfill_end_date(now())
            try:
                result = backfill_instrument_history(
                    db,
                    code,
                    end_date=target_end,
                    collected_at=now(),
                    apply=args.apply,
                )
            except ValueError as exc:
                failures.append({"code": code, "error": str(exc)})
                report_items[code] = {"status": "failed", "error": str(exc)}
                print(f"[FAIL] {code}: {exc}")
                time.sleep(0.35)
                continue

            report_items[code] = result
            print(
                f"[OK] {code} ({instrument.name}): source={result['selected_source']}, "
                f"{result['listing_start']}..{result['end']} ({result['total_rows']}条), "
                f"待回补={result['backfill_candidates']}条, "
                f"overlap={result['overlap_check']['overlap_days']}天"
            )
            time.sleep(0.35)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "applied": args.apply,
                "instrument_count": len(report_items),
                "failure_count": len(failures),
                "failures": failures,
                "items": report_items,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"报告已写入 {args.report}；失败 {len(failures)} 只。")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
