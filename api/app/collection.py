"""分月查询、行情校验和可恢复的幂等采集。"""

import calendar
import os
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import Session
from app.models import Candle, Instrument, Run, Window

TZ = ZoneInfo("Asia/Shanghai")


def now():
    """返回带时区的本地业务时间。"""
    return datetime.now(TZ)


def month_ranges(start, end):
    """将闭区间按自然月拆分，限制单次源请求大小。"""
    while start <= end:
        last = min(
            end,
            date(
                start.year, start.month, calendar.monthrange(start.year, start.month)[1]
            ),
        )
        yield start, last
        start = last + timedelta(days=1)


def validate_row(row, code, start, end):
    """校验源数据边界及价格关系，返回可入库字段。"""
    if not isinstance(row, dict):
        raise ValueError("源行情记录不是对象")  # noqa: TRY004 — 源数据校验统一使用 ValueError
    try:
        day = date.fromisoformat(row["TRADE_DATE"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("交易日期缺失或非法") from None
    if row.get("STOCK_CODE") != code or not start <= day <= end:
        raise ValueError("返回标的或日期超出请求范围")
    result = {"code": code, "date": day}
    for dest, src in [
        ("open", "OPEN_PRICE"),
        ("high", "HIGH_PRICE"),
        ("low", "LOW_PRICE"),
        ("close", "CLOSE_PRICE"),
        ("volume", "VOLUME"),
        ("amount", "AMOUNT"),
    ]:
        try:
            value = Decimal(str(row[src]))
        except (InvalidOperation, KeyError):
            raise ValueError("必要行情字段缺失或非法") from None
        if (
            not value.is_finite()
            or value < 0
            or (dest in ["open", "high", "low", "close"] and value == 0)
        ):
            raise ValueError("价格或成交量额非法")
        result[dest] = value
    if (
        not result["low"]
        <= min(result["open"], result["close"])
        <= max(result["open"], result["close"])
        <= result["high"]
    ):
        raise ValueError("最高最低价关系错误")
    for dest, src in [
        ("change_pct", "CHANGE_PCT"),
        ("adjusted_close", "ADJUSTED_CLOSE"),
    ]:
        value = row.get(src)
        result[dest] = Decimal(str(value)) if value is not None else None
        if result[dest] is not None and not result[dest].is_finite():
            raise ValueError("可选行情字段非法")
    result.update(source_updated_at=row.get("SOURCE_UPDATED_AT"), collected_at=now())
    return result


def fetch_rows(code, start, end):
    """只读查询数据源，有限重试且不向调用方暴露鉴权信息。"""
    token, access = os.getenv("CHATBI_TOKEN"), os.getenv("CHATBI_ACCESS_CODE")
    if not token or not access:
        raise ValueError("请配置后端 CHATBI_TOKEN 和 CHATBI_ACCESS_CODE")
    for attempt in range(3):
        try:
            response = httpx.post(
                os.getenv(
                    "CHATBI_URL", "https://chatbi.cnht.com.cn/api/sqlapi/api-execute"
                ),
                params={"api_path": "daily_ohlcv_etf", "access_code": access},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "stockcodelist": [code],
                    "start_date": str(start),
                    "end_date": str(end),
                },
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            )
            if response.status_code in (401, 403):
                raise ValueError("数据源鉴权失败，请检查后端凭据")
            if response.status_code >= 500 or response.status_code == 429:
                raise httpx.TransportError("临时服务错误")
            if response.status_code != 200:
                raise ValueError(f"数据源 HTTP {response.status_code}")
            body = response.json()
            if (
                not isinstance(body, dict)
                or body.get("success") is not True
                or not isinstance(body.get("data"), list)
            ):
                raise ValueError("数据源返回执行失败或格式错误")
            return body["data"]
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("数据源网络请求失败，已重试三次") from None
            time.sleep(attempt + 1)
        except (TypeError, KeyError):
            raise ValueError("数据源返回格式错误") from None


def collect(run_id, fetch=fetch_rows):
    """按区间提交，失败不推进水位，后续运行可恢复缺口。"""
    cutoff = now().date() - timedelta(days=1)
    failures = successes = 0
    with Session() as db:
        run = db.get(Run, run_id)
        instruments = db.scalars(
            select(Instrument).where(Instrument.enabled.is_(True))
        ).all()
        for instrument in instruments:
            for start, end in month_ranges(instrument.start_date, cutoff):
                previous = db.get(Window, (instrument.code, start))
                if (
                    previous
                    and previous.end >= end
                    and end < cutoff - timedelta(days=7)
                ):
                    continue
                query_start = start
                if previous:
                    query_start = max(
                        start, min(previous.end, cutoff) - timedelta(days=7)
                    )
                try:
                    rows = fetch(instrument.code, query_start, end)
                    values = [
                        validate_row(row, instrument.code, query_start, end)
                        for row in rows
                    ]
                    for value in values:
                        physical_values = {
                            getattr(Candle, key).property.columns[0].name: item
                            for key, item in value.items()
                        }
                        statement = insert(Candle.__table__).values(**physical_values)
                        db.execute(
                            statement.on_conflict_do_update(
                                index_elements=["instrument_code", "trade_date"],
                                set_={
                                    k: getattr(statement.excluded, k)
                                    for k in physical_values
                                    if k not in ("instrument_code", "trade_date")
                                },
                            )
                        )
                    if rows and rows[-1].get("STOCK_NAME"):
                        instrument.name = rows[-1]["STOCK_NAME"]
                    if previous:
                        previous.end = end
                    else:
                        db.add(Window(code=instrument.code, start=start, end=end))
                    successes += 1
                    entry = {
                        "code": instrument.code,
                        "start": str(query_start),
                        "end": str(end),
                        "status": "success",
                        "count": len(rows),
                        "message": "空响应，不代表完整性验证" if not rows else "已入库",
                    }
                except (ValueError, KeyError, InvalidOperation) as exc:
                    db.rollback()
                    # 复查失败也必须重试，不能继续沿用旧成功区间跳过该月。
                    failed_window = db.get(Window, (instrument.code, start))
                    if failed_window is not None:
                        db.delete(failed_window)
                    failures += 1
                    entry = {
                        "code": instrument.code,
                        "start": str(query_start),
                        "end": str(end),
                        "status": "failed",
                        "count": 0,
                        "message": str(exc)
                        if isinstance(exc, ValueError)
                        else "源字段非法",
                    }
                run.logs = [*run.logs, entry]
                db.commit()
        run.status = ("partial" if successes else "failed") if failures else "success"
        run.ended_at = now()
        db.commit()
