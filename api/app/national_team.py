"""国家队ETF比例采集：固定请求基准，全量核验、增量写入，不保存源价格。"""

import re
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select

from app.collection import now
from app.db import Session
from app.models import NationalTeamDaily, NationalTeamInstrument, Run

SOURCE_URL = "https://ai2.jiucaishuo.com/api/tools/national-team-etf"
ESTIMATION_START = date(2026, 1, 1)
INSTRUMENT_CODES = (
    "510300",
    "510330",
    "510310",
    "159919",
    "510050",
    "510180",
    "510500",
    "512500",
    "159922",
    "159845",
    "512100",
    "560010",
    "159629",
    "159915",
    "159952",
    "159977",
    "588080",
    "588050",
)


def source_get(params):
    """向固定只读源发送查询，网络或限流错误最多重试三次。

    Args:
        params: 固定估算起点和本次北京时间截止日期。

    Returns:
        原始JSON对象；业务字段在后续完整校验。
    """
    for attempt in range(3):
        try:
            response = httpx.get(
                SOURCE_URL,
                params=params,
                timeout=60,
                trust_env=False,
                follow_redirects=False,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.TransportError("源暂时不可用")
            if response.status_code != 200:
                raise ValueError(f"国家队源HTTP {response.status_code}")
            return response.json()
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("国家队数据源网络错误，三次请求均失败") from None
            time.sleep(attempt + 1)
        except ValueError:
            raise ValueError("国家队源响应状态或JSON格式无效") from None


def numeric(value, *, maximum=None):
    """转换有限非负源数值，拒绝布尔值及伪数值。"""
    try:
        if value is None or isinstance(value, bool):
            raise ValueError("源数值缺失或非法")
        result = Decimal(str(value))
        if (
            not result.is_finite()
            or result < 0
            or (maximum is not None and result > maximum)
        ):
            raise ValueError("源数值超出有效范围")
        return result
    except (InvalidOperation, TypeError):
        raise ValueError("源数值格式非法") from None


def validate_response(body, end):
    """验证源成功状态、固定估算范围和代码唯一性。"""
    if not isinstance(body, dict) or body.get("code") != 0:
        raise ValueError("国家队源业务状态无效")
    data = body.get("data")
    if not isinstance(data, dict) or (
        data.get("start") != str(ESTIMATION_START) or data.get("end") != str(end)
    ):
        raise ValueError("源请求范围或估算基准不一致，拒绝混合不同口径")
    items = data.get("etfs")
    if not isinstance(items, list) or not items:
        raise ValueError("源ETF目录为空")
    result = {}
    for item in items:
        code = item.get("code") if isinstance(item, dict) else None
        if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
            raise ValueError("源ETF代码非法")
        if code in result:
            raise ValueError("源ETF代码重复")
        result[code] = item
    return result


def validate_etf(item, end):
    """完整校验单ETF，缺失份额不转换成零持仓，源价格不持久化。

    Returns:
        目录业务字段与按源日期排序的比例记录。

    Raises:
        ValueError: 源字段、日期、比例非法或同日记录冲突。
    """
    code = item.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise ValueError("源ETF代码非法")
    if any(
        not isinstance(item.get(k), str) or not item[k].strip()
        for k in ("name", "index")
    ):
        raise ValueError("源ETF名称或指数名称缺失")
    reference = item.get("hold_pct")
    meta = {
        "instrument_code": code,
        "instrument_name": item["name"],
        "index_name": item["index"],
        "estimation_start_date": ESTIMATION_START,
        "reference_holding_pct": numeric(reference, maximum=100).quantize(
            Decimal(".00000001")
        )
        if reference is not None
        else None,
        "source_url": SOURCE_URL,
    }
    points = item.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("源ETF历史为空，保留原数据")
    rows = {}
    for point in points:
        if not isinstance(point, dict):
            raise TypeError("源日数据格式非法")
        try:
            raw_day = point.get("date")
            day = datetime.fromisoformat(raw_day).date()
        except (ValueError, TypeError):
            raise ValueError("源交易日期非法") from None
        if not ESTIMATION_START <= day <= end:
            raise ValueError("源日期不在固定请求范围内")
        shares = numeric(point.get("fe"))
        ratio = point.get("nat_pct")
        ratio = (
            numeric(ratio, maximum=100).quantize(Decimal(".00000001"))
            if ratio is not None
            else None
        )
        row = {
            "instrument_code": code,
            "trade_date": day,
            "estimated_holding_pct": ratio if shares > 0 else None,
        }
        if day in rows and rows[day] != row:
            raise ValueError("源同日比例存在冲突")
        rows[day] = row
    return meta, [rows[day] for day in sorted(rows)]


def collect_national_team(run_id, fetch=source_get):
    """固定基准核验十八只基金，逐基金事务隔离，仅写新增和修订记录。"""
    end = now().date()
    with Session() as db:
        run = db.get(Run, run_id)
        try:
            items = validate_response(
                fetch({"start": str(ESTIMATION_START), "end": str(end)}), end
            )
        except (ValueError, TypeError):
            run.logs = [
                {
                    "status": "failed",
                    "count": 0,
                    "message": "源目录获取或估算基准校验失败，保留已有数据",
                }
            ]
            run.status, run.ended_at = "failed", now()
            db.commit()
            return
        for stored in db.scalars(select(NationalTeamInstrument)):
            stored.source_available = stored.instrument_code in items
        db.commit()
        successes = failures = 0
        for code in INSTRUMENT_CODES:
            entry = {"code": code, "start": str(ESTIMATION_START), "end": str(end)}
            try:
                if code not in items:
                    raise ValueError("本次源目录缺少该ETF，保留历史等待重试")
                meta, rows = validate_etf(items[code], end)
                stored = db.get(NationalTeamInstrument, code)
                if stored and stored.estimation_start_date != ESTIMATION_START:
                    raise ValueError("本地估算基准不同，拒绝覆盖历史")
                previous = {
                    r.trade_date: r
                    for r in db.scalars(
                        select(NationalTeamDaily).where(
                            NationalTeamDaily.instrument_code == code
                        )
                    )
                }
                source_days = {r["trade_date"] for r in rows}
                if previous.keys() - source_days:
                    raise ValueError("源历史缺日或截止日倒退，保留原数据等待重试")
                if not stored:
                    stored = NationalTeamInstrument(
                        **meta, source_available=True, last_success_at=now()
                    )
                    db.add(stored)
                    db.flush()
                else:
                    for key, value in meta.items():
                        setattr(stored, key, value)
                inserted = revised = 0
                for row in rows:
                    old = previous.get(row["trade_date"])
                    if old is None:
                        db.add(NationalTeamDaily(**row, collected_at=now()))
                        inserted += 1
                    elif old.estimated_holding_pct != row["estimated_holding_pct"]:
                        old.estimated_holding_pct = row["estimated_holding_pct"]
                        old.collected_at = now()
                        revised += 1
                stored.source_available, stored.last_success_at = True, now()
                entry.update(
                    status="success",
                    count=inserted + revised,
                    inserted=inserted,
                    revised=revised,
                    source_last_date=str(rows[-1]["trade_date"]),
                    message=f"新增{inserted}条，修订{revised}条，未变{len(rows) - inserted - revised}条；固定基准核验",
                )
                db.commit()
                successes += 1
            except (ValueError, TypeError, KeyError) as exc:
                db.rollback()
                failures += 1
                entry.update(
                    status="failed",
                    count=0,
                    message=str(exc)
                    if isinstance(exc, ValueError)
                    else "源字段格式非法",
                )
            run = db.get(Run, run_id)
            run.logs = [*run.logs, entry]
            db.commit()
        run.status = ("partial" if successes else "failed") if failures else "success"
        run.ended_at = now()
        db.commit()
