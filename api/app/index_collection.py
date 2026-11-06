"""独立指数估值全历史核验、增量写入及指数日K窗口恢复。"""

import hashlib
import json
from datetime import timedelta
from decimal import Context, Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.collection import fetch_rows, month_ranges, now, validate_row
from app.db import Session
from app.index_valuation import METRICS, parse_history, source_get
from app.models import (
    IndexCandle,
    IndexCollectionWindow,
    IndexValuationDaily,
    IndexValuationRevision,
    IndexValuationSnapshot,
    ResearchIndex,
    Run,
)


def fetch_index_candles(code, start, end):
    """使用已有后端凭据查询独立的指数日行情接口。"""
    return fetch_rows(code, start, end, api_path="daily_ohlcv_index")


def save_history(db, code, metric, rows, run_id):
    """原子保存单指标新增/修订及证据；源缺日或回退拒绝整个指标。

    Returns:
        新增数和修订数，未变化数据不重写时间。
    """
    previous = {
        r.trade_date: r
        for r in db.scalars(
            select(IndexValuationDaily).where(
                IndexValuationDaily.index_code == code,
                IndexValuationDaily.metric_key == metric,
            )
        )
    }
    missing = previous.keys() - {r[0] for r in rows}
    today = now().date()
    try:
        boundary = today.replace(year=today.year - 10)
    except ValueError:
        boundary = today.replace(year=today.year - 10, day=28)
    if missing and (
        max(missing) >= boundary
        or max(missing) >= rows[0][0]
        or rows[-1][0] < max(previous)
        or rows[0][0] > max(previous)
    ):
        raise ValueError("源历史缺日或日期倒退，保留本地历史等待重试")
    stamp = now()
    inserted = revised = 0
    additions, revisions = [], []
    for day, raw_value, status in rows:
        value = (
            raw_value.quantize(Decimal("1e-18"), context=Context(prec=40))
            if raw_value is not None
            else None
        )
        old = previous.get(day)
        if old is not None and old.metric_value == value and old.value_status == status:
            continue
        revisions.append(
            {
                "index_code": code,
                "metric_key": metric,
                "trade_date": day,
                "old_value": old.metric_value if old else None,
                "new_value": value,
                "old_status": old.value_status if old else None,
                "new_status": status,
                "observed_at": stamp,
                "run_id": run_id,
            }
        )
        if old is None:
            additions.append(
                {
                    "index_code": code,
                    "metric_key": metric,
                    "trade_date": day,
                    "metric_value": value,
                    "value_status": status,
                    "collected_at": stamp,
                }
            )
            inserted += 1
        else:
            old.metric_value, old.value_status, old.collected_at = value, status, stamp
            revised += 1
    if additions:
        db.execute(insert(IndexValuationDaily), additions)
    if revisions:
        db.execute(insert(IndexValuationRevision), revisions)
    return inserted, revised


def save_snapshot(db, code, payload, run_id):
    """相邻内容相同不重复归档，内容再次改变仍保留新的观测时刻。"""
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    last = db.scalar(
        select(IndexValuationSnapshot)
        .where(IndexValuationSnapshot.index_code == code)
        .order_by(IndexValuationSnapshot.snapshot_id.desc())
        .limit(1)
    )
    if last is None or last.content_sha256 != digest:
        db.add(
            IndexValuationSnapshot(
                index_code=code,
                content_sha256=digest,
                source_payload=payload,
                observed_at=now(),
                run_id=run_id,
            )
        )


def log_entry(db, run_id, entry):
    """每一阶段落库进度，使重启和页面可见已完成部分。"""
    run = db.get(Run, run_id)
    run.logs = [*run.logs, entry]
    db.commit()


def collect_candles(db, item, run_id, fetch):
    """从最早有效估值按月查询指数日K；失败撤销水位，保留七日交叠。"""
    code = item.index_code
    first = db.scalar(
        select(func.min(IndexValuationDaily.trade_date)).where(
            IndexValuationDaily.index_code == code,
            IndexValuationDaily.value_status == "valid",
        )
    )
    if first is None:
        return 0, 0
    cutoff = now().date() - timedelta(days=1)
    successes = failures = 0
    for start, end in month_ranges(first, cutoff):
        expected = set(
            db.scalars(
                select(IndexValuationDaily.trade_date)
                .where(
                    IndexValuationDaily.index_code == code,
                    IndexValuationDaily.value_status == "valid",
                    IndexValuationDaily.trade_date >= start,
                    IndexValuationDaily.trade_date <= end,
                )
                .distinct()
            )
        )
        stored_days = set(
            db.scalars(
                select(IndexCandle.trade_date).where(
                    IndexCandle.index_code == code,
                    IndexCandle.trade_date >= start,
                    IndexCandle.trade_date <= end,
                )
            )
        )
        old_window = db.get(IndexCollectionWindow, (code, start))
        if (
            old_window
            and old_window.collection_end_date >= end
            and end < cutoff - timedelta(days=7)
            and not (expected - stored_days)
        ):
            continue
        query_start = (
            max(start, min(old_window.collection_end_date, cutoff) - timedelta(days=7))
            if old_window
            else start
        )
        if expected - stored_days:
            query_start = min(query_start, min(expected - stored_days))
        entry = {"code": code, "start": str(query_start), "end": str(end)}
        try:
            rows = fetch(item.chatbi_code, query_start, end)
            values, dates = [], set()
            for row in rows:
                value = validate_row(row, item.chatbi_code, query_start, end)
                day = value.pop("date")
                if day in dates:
                    raise ValueError("指数行情同日记录重复")
                dates.add(day)
                values.append(
                    {
                        "index_code": code,
                        "trade_date": day,
                        "open_price": value["open"],
                        "high_price": value["high"],
                        "low_price": value["low"],
                        "close_price": value["close"],
                        "trading_volume": value["volume"],
                        "trading_amount": value["amount"],
                        "price_change_pct": value["change_pct"],
                        "source_updated_at": value["source_updated_at"],
                        "collected_at": value["collected_at"],
                    }
                )
            required = {day for day in expected if query_start <= day <= end}
            if required - dates:
                raise ValueError("估值交易日缺少对应指数日K，本区间等待回补")
            if values:
                statement = insert(IndexCandle).values(values)
                keys = [
                    k
                    for k in values[0]
                    if k not in ("index_code", "trade_date", "collected_at")
                ]
                db.execute(
                    statement.on_conflict_do_update(
                        index_elements=["index_code", "trade_date"],
                        set_={
                            k: getattr(statement.excluded, k)
                            for k in keys + ["collected_at"]
                        },
                        where=IndexCandle.__table__.c.close_price.is_distinct_from(
                            statement.excluded.close_price
                        )
                        | IndexCandle.__table__.c.open_price.is_distinct_from(
                            statement.excluded.open_price
                        )
                        | IndexCandle.__table__.c.high_price.is_distinct_from(
                            statement.excluded.high_price
                        )
                        | IndexCandle.__table__.c.low_price.is_distinct_from(
                            statement.excluded.low_price
                        )
                        | IndexCandle.__table__.c.trading_volume.is_distinct_from(
                            statement.excluded.trading_volume
                        )
                        | IndexCandle.__table__.c.trading_amount.is_distinct_from(
                            statement.excluded.trading_amount
                        )
                        | IndexCandle.__table__.c.price_change_pct.is_distinct_from(
                            statement.excluded.price_change_pct
                        )
                        | IndexCandle.__table__.c.source_updated_at.is_distinct_from(
                            statement.excluded.source_updated_at
                        ),
                    )
                )
            if old_window:
                old_window.collection_end_date = end
            else:
                db.add(
                    IndexCollectionWindow(
                        index_code=code,
                        collection_start_date=start,
                        collection_end_date=end,
                    )
                )
            entry.update(
                status="success",
                count=len(values),
                message="指数日K入库"
                if values
                else "空响应；不代表历史完整，实际覆盖见页面",
            )
            db.commit()
            successes += 1
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            db.rollback()
            window = db.get(IndexCollectionWindow, (code, start))
            if window:
                db.delete(window)
            entry.update(
                status="failed",
                count=0,
                message=f"指数日K请求或校验失败：{exc if isinstance(exc, ValueError) else '源数值格式非法'}；本区间等待重试",
            )
            failures += 1
        log_entry(db, run_id, entry)
    return successes, failures


def collect_indices(run_id, fetch=source_get, fetch_candles=fetch_index_candles):
    """任务4分阶段采集，单指标失败不阻塞其他指标或指数；无行情凭据不报全成功。"""
    successes = failures = 0
    overview = {}
    with Session() as db:
        for category in ("gm", "jx"):
            try:
                body = fetch("", {"category": category})
                if not isinstance(body.get("rows"), list):
                    raise ValueError("源概览格式错误")  # noqa: TRY004 — 源格式校验统一使用ValueError
                overview.update({row["code"]: row for row in body["rows"]})
            except (ValueError, TypeError, KeyError):
                failures += 1
                log_entry(
                    db,
                    run_id,
                    {
                        "status": "failed",
                        "count": 0,
                        "message": f"{category}来源概览读取失败，历史仍继续采集",
                    },
                )
        items = db.scalars(
            select(ResearchIndex).where(ResearchIndex.collection_enabled.is_(True))
        ).all()
        for item in items:
            code = item.index_code
            payload = {"overview": overview.get(code), "detail": None, "history": {}}
            try:
                detail = fetch("/detail", {"code": code})
                if detail.get("header", {}).get("code") != code:
                    raise ValueError("源详情代码不匹配")
                payload["detail"] = detail
            except (ValueError, TypeError, KeyError):
                failures += 1
                log_entry(
                    db,
                    run_id,
                    {
                        "code": code,
                        "status": "failed",
                        "count": 0,
                        "message": "指数详情读取失败；历史继续采集",
                    },
                )
            for metric in METRICS:
                entry = {"code": code}
                try:
                    body = fetch("/history", {"code": code, "metric": metric})
                    rows = parse_history(body, code, metric)
                    inserted, revised = save_history(db, code, metric, rows, run_id)
                    payload["history"][metric] = {
                        **{
                            key: value for key, value in body.items() if key != "series"
                        },
                        "first_date": str(rows[0][0]),
                        "last_date": str(rows[-1][0]),
                        "count": len(rows),
                        "invalid_count": sum(r[2] != "valid" for r in rows),
                    }
                    db.commit()
                    successes += 1
                    entry.update(
                        status="success",
                        count=inserted + revised,
                        start=str(rows[0][0]),
                        end=str(rows[-1][0]),
                        message=f"{METRICS[metric][0]}：新增{inserted}，修订{revised}，未变{len(rows) - inserted - revised}；十年窗口以前源点不再返回时保留本地记录",
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    db.rollback()
                    failures += 1
                    entry.update(
                        status="failed",
                        count=0,
                        message=f"{METRICS[metric][0]}：{exc}"
                        if isinstance(exc, ValueError)
                        else "源历史格式非法",
                    )
                log_entry(db, run_id, entry)
            # 部分失败不以不完整快照覆盖此前完整摘要。
            if (
                payload["overview"] is not None
                and payload["detail"] is not None
                and len(payload["history"]) == len(METRICS)
            ):
                save_snapshot(db, code, payload, run_id)
                db.commit()
            good, bad = collect_candles(db, item, run_id, fetch_candles)
            successes += good
            failures += bad
        run = db.get(Run, run_id)
        run.status = ("partial" if successes else "failed") if failures else "success"
        run.ended_at = now()
        db.commit()
