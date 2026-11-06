"""行业恐贪首次历史回补与后续增量采集，源接口最小有效窗口为一年。"""

import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.collection import now
from app.db import Session
from app.models import Run, SentimentCategory, SentimentDaily

SOURCE_URL = "https://ai2.jiucaishuo.com/api/tools/industry-fear-greed"


def request_years(last_date: date | None, current_date: date) -> int:
    """按已入库日期选择源支持的最小1/3/5年窗口，预留七日修订交叠。"""
    if last_date is None:
        return 5
    days = (current_date - last_date).days + 7
    return 1 if days < 365 else 3 if days < 3 * 365 else 5


def source_get(path="", params=None):
    """仅查询固定源地址；有限重试，不跟随重定向。"""
    for attempt in range(3):
        try:
            response = httpx.get(
                SOURCE_URL + path,
                params=params,
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.TransportError("临时服务错误")
            if response.status_code != 200:
                raise ValueError(f"恐贪数据源 HTTP {response.status_code}")
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("恐贪数据源响应不是对象")
            return body
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("恐贪数据源网络错误，三次请求均失败") from None
            time.sleep(attempt + 1)
        except (ValueError, TypeError) as exc:
            raise ValueError("恐贪数据源响应格式或状态无效") from exc


def number(value, label, *, nullable=False, maximum=None):
    """将源数值转换为有限定点数，区分零值与缺失。"""
    if value is None and nullable:
        return None
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label}缺失或非法")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label}不是有效数值") from None
    if (
        not result.is_finite()
        or result < 0
        or (maximum is not None and result > maximum)
    ):
        raise ValueError(f"{label}超出有效范围")
    return result


def validate_series(body, category_key):
    """完整校验单类别序列，日期冲突或非法记录使该类别本次不入库。"""
    if (
        not isinstance(body, dict)
        or body.get("key") != category_key
        or not isinstance(body.get("series"), list)
    ):
        raise ValueError("源类别不匹配或历史序列缺失")
    result = {}
    for row in body["series"]:
        if not isinstance(row, dict):
            raise TypeError("历史序列记录格式非法")
        try:
            day = date.fromisoformat(row.get("date"))
        except (ValueError, TypeError):
            raise ValueError("源日期缺失或格式非法") from None
        if day > now().date():
            raise ValueError("源日期晚于当前日期")
        value = {
            "category_key": category_key,
            "trade_date": day,
            "fear_greed_score": number(row.get("value"), "恐贪分数", maximum=100),
            "close_price": number(row.get("close"), "指数收盘点位", nullable=True),
        }
        if day in result and result[day] != value:
            raise ValueError("同一日期存在冲突数据")
        result[day] = value
    return [result[day] for day in sorted(result)]


def collect_sentiment(run_id, fetch=source_get):
    """目录独立提交，类别原子更新；失败不推进最新日期，下一次继续补采。"""
    with Session() as db:
        run = db.get(Run, run_id)
        try:
            directory = fetch()
            if not isinstance(directory.get("items"), list) or not directory["items"]:
                raise ValueError("源类别目录为空或格式无效")
            keys = set()
            for item in directory["items"]:
                key, name = item.get("key"), item.get("name")
                if (
                    not isinstance(key, str)
                    or not key
                    or len(key) > 64
                    or not isinstance(name, str)
                    or not name
                ):
                    raise ValueError("源类别标识或名称非法")
                if key in keys:
                    raise ValueError("源类别目录包含重复标识")
                keys.add(key)
                category = db.get(SentimentCategory, key)
                if category is None:
                    category = SentimentCategory(
                        category_key=key, category_name=name, collected_at=now()
                    )
                    db.add(category)
                category.category_name, category.collected_at = name, now()
                try:
                    category.snapshot_date = date.fromisoformat(item.get("date"))
                    category.snapshot_score = number(
                        item.get("value"), "快照分数", maximum=100
                    )
                    category.snapshot_label = (
                        item.get("desc") if isinstance(item.get("desc"), str) else None
                    )
                except (TypeError, ValueError):
                    category.snapshot_date = category.snapshot_score = (
                        category.snapshot_label
                    ) = None
            db.commit()
        except (ValueError, TypeError, AttributeError):
            db.rollback()
            run.logs = [
                {"status": "failed", "message": "类别目录获取或校验失败，请重试"}
            ]
            run.status, run.ended_at = "failed", now()
            db.commit()
            return
        categories = db.scalars(
            select(SentimentCategory).where(
                SentimentCategory.collection_enabled.is_(True)
            )
        ).all()
        successes = failures = 0
        for category in categories:
            key = category.category_key
            last_date = db.scalar(
                select(func.max(SentimentDaily.trade_date)).where(
                    SentimentDaily.category_key == key
                )
            )
            years = request_years(last_date, now().date())
            entry = {
                "code": key,
                "years": years,
                "mode": "initial" if last_date is None else "incremental",
            }
            try:
                body = fetch("/series", {"key": key, "years": years})
                rows = validate_series(body, key)
                start = last_date - timedelta(days=7) if last_date else None
                # 超过源五年历史上限的断档不得静默推进，保留原水位并提示人工核实。
                if (
                    last_date
                    and rows
                    and last_date < rows[0]["trade_date"] - timedelta(days=7)
                ):
                    raise ValueError(
                        "源历史窗口未覆盖已存日期，存在断档，请核实数据源历史上限"
                    )
                values = [
                    row for row in rows if start is None or row["trade_date"] >= start
                ]
                if not rows or not values:
                    raise ValueError("源序列为空或未返回增量区间，保留原数据并等待重试")
                if last_date and rows[-1]["trade_date"] < last_date:
                    raise ValueError("源数据截止日期早于本地水位，保留原数据并等待重试")
                collected_at = now()
                for row in values:
                    statement = insert(SentimentDaily).values(
                        **row, collected_at=collected_at
                    )
                    db.execute(
                        statement.on_conflict_do_update(
                            index_elements=["category_key", "trade_date"],
                            set_={
                                name: getattr(statement.excluded, name)
                                for name in [
                                    "fear_greed_score",
                                    "close_price",
                                    "collected_at",
                                ]
                            },
                        )
                    )
                if isinstance(body.get("index_name"), str):
                    category.index_name = body["index_name"]
                entry.update(
                    status="success",
                    count=len(values),
                    fetched_count=len(rows),
                    start=str(values[0]["trade_date"]),
                    end=str(values[-1]["trade_date"]),
                    message=f"{'首次五年回补' if last_date is None else '增量更新'}；源返回{len(rows)}条，入库{len(values)}条（含修订交叠）",
                )
                successes += 1
            except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
                db.rollback()
                failures += 1
                entry.update(
                    status="failed",
                    count=0,
                    message=str(exc)
                    if isinstance(exc, ValueError)
                    else "源数据字段非法",
                )
            run.logs = [*run.logs, entry]
            db.commit()
        run.status = ("partial" if successes else "failed") if failures else "success"
        run.ended_at = now()
        db.commit()
