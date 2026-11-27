"""全市场恐贪总分及五维环境子因子的增量采集。"""

import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.collection import now
from app.db import Session
from app.models import MarketFearGreedDaily, MarketRegimeFactorDaily, Run

SOURCE_URL = "https://ai2.jiucaishuo.com/api/fear-greed"
FACTOR_KEYS = ("volatility", "bx", "premium", "wz", "strength")


def source_get():
    """读取无需凭据的全市场恐贪源，有限重试且不继承代理环境。"""
    for attempt in range(3):
        try:
            response = httpx.get(
                SOURCE_URL,
                params={"type": "all"},
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.TransportError("临时服务错误")
            if response.status_code != 200:
                raise ValueError(f"全市场恐贪数据源 HTTP {response.status_code}")
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("全市场恐贪数据源响应不是对象")
            return body
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("全市场恐贪数据源网络错误，三次请求均失败") from None
            time.sleep(attempt + 1)
        except (ValueError, TypeError) as exc:
            raise ValueError("全市场恐贪数据源响应格式或状态无效") from exc


def _date(value, label, current_date):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}日期缺失或格式非法") from None
    if parsed > current_date:
        raise ValueError(f"{label}日期晚于当前日期")
    return parsed


def _number(value, label, *, minimum=None, maximum=None, nullable=False):
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
        or (minimum is not None and result < minimum)
        or (maximum is not None and result > maximum)
    ):
        raise ValueError(f"{label}超出有效范围")
    return result


def validate_response(body, current_date):
    """校验源总分与五维子因子，返回可原样落库的有序观测。"""
    if not isinstance(body, dict):
        raise TypeError("全市场恐贪响应不是对象")
    latest_day = _date(body.get("date"), "全市场恐贪快照", current_date)
    latest_score = _number(
        body.get("value"), "全市场恐贪分数", minimum=0, maximum=100
    )
    latest_label = body.get("desc")
    if latest_label is not None and (
        not isinstance(latest_label, str) or len(latest_label) > 32
    ):
        raise ValueError("全市场恐贪标签非法")

    history = body.get("history")
    if not isinstance(history, list) or not history:
        raise ValueError("全市场恐贪历史序列为空或格式非法")
    totals = {}
    for item in history:
        if not isinstance(item, dict):
            raise TypeError("全市场恐贪历史记录格式非法")
        item_day = _date(item.get("date"), "全市场恐贪历史", current_date)
        item_score = _number(
            item.get("value"), "全市场恐贪历史分数", minimum=0, maximum=100
        )
        value = {
            "trade_date": item_day,
            "fear_greed_score": item_score,
            "source_label": (
                latest_label
                if item_day == latest_day and item_score == latest_score
                else None
            ),
        }
        if item_day in totals and totals[item_day] != value:
            raise ValueError("全市场恐贪历史日期存在冲突")
        totals[item_day] = value

    factors = body.get("factors")
    if not isinstance(factors, list):
        raise TypeError("全市场环境子因子缺失或格式非法")
    seen_keys, regimes = set(), {}
    for factor in factors:
        if not isinstance(factor, dict):
            raise TypeError("全市场环境子因子格式非法")
        key, name, series = factor.get("key"), factor.get("name"), factor.get("series")
        if (
            not isinstance(key, str)
            or key not in FACTOR_KEYS
            or key in seen_keys
            or not isinstance(name, str)
            or not name
            or len(name) > 100
            or not isinstance(series, list)
            or not series
        ):
            raise ValueError("全市场环境五项子因子格式非法")
        seen_keys.add(key)
        for item in series:
            if not isinstance(item, dict):
                raise TypeError("全市场环境子因子序列格式非法")
            item_day = _date(item.get("date"), f"{key}子因子", current_date)
            value = {
                "factor_key": key,
                "trade_date": item_day,
                "factor_name": name,
                "raw_value": _number(item.get("value"), f"{key}原始值"),
                "source_pct_year": _number(
                    item.get("pct_year"),
                    f"{key}近一年分位",
                    minimum=0,
                    maximum=100,
                    nullable=True,
                ),
                "source_pct_all": _number(
                    item.get("pct_all"),
                    f"{key}全历史分位",
                    minimum=0,
                    maximum=100,
                    nullable=True,
                ),
            }
            identity = (key, item_day)
            if identity in regimes and regimes[identity] != value:
                raise ValueError("全市场环境子因子日期存在冲突")
            regimes[identity] = value
    if seen_keys != set(FACTOR_KEYS):
        raise ValueError("全市场环境必须包含五项子因子")
    return (
        [totals[item_day] for item_day in sorted(totals)],
        [regimes[identity] for identity in sorted(regimes)],
    )


def _sync_total_rows(db, rows, collected_at):
    inserted = revised = 0
    for item in rows:
        existing = db.get(MarketFearGreedDaily, item["trade_date"])
        if existing is None:
            db.add(MarketFearGreedDaily(**item, collected_at=collected_at))
            inserted += 1
        elif (
            existing.fear_greed_score != item["fear_greed_score"]
            or existing.source_label != item["source_label"]
        ):
            existing.fear_greed_score = item["fear_greed_score"]
            existing.source_label = item["source_label"]
            existing.collected_at = collected_at
            revised += 1
    return inserted, revised


def _sync_regime_rows(db, rows, collected_at):
    summaries = {}
    for key in FACTOR_KEYS:
        items = [item for item in rows if item["factor_key"] == key]
        inserted = revised = 0
        for item in items:
            existing = db.get(MarketRegimeFactorDaily, (key, item["trade_date"]))
            if existing is None:
                db.add(MarketRegimeFactorDaily(**item, collected_at=collected_at))
                inserted += 1
            elif any(
                getattr(existing, field) != item[field]
                for field in ("factor_name", "raw_value", "source_pct_year", "source_pct_all")
            ):
                for field, value in item.items():
                    setattr(existing, field, value)
                existing.collected_at = collected_at
                revised += 1
        summaries[key] = (inserted, revised, items)
    return summaries


def _log(scope, inserted, revised, rows):
    return {
        "scope": scope,
        "status": "success",
        "count": inserted + revised,
        "inserted": inserted,
        "revised": revised,
        "start": str(rows[0]["trade_date"]),
        "end": str(rows[-1]["trade_date"]),
        "message": "已核验并按源日期增量保存",
    }


def collect_market_sentiment(run_id, fetch=source_get):
    """采集并幂等修订全市场观测，子因子短窗口绝不删除本地旧历史。"""
    with Session() as db:
        run = db.get(Run, run_id)
        if run is None:
            raise ValueError("运行记录不存在")
        try:
            collected_at = now()
            total_rows, regime_rows = validate_response(fetch(), collected_at.date())
            total_inserted, total_revised = _sync_total_rows(
                db, total_rows, collected_at
            )
            summaries = _sync_regime_rows(db, regime_rows, collected_at)
            run.logs = [
                _log("market_fear_greed", total_inserted, total_revised, total_rows),
                *[
                    _log(key, inserted, revised, rows)
                    for key, (inserted, revised, rows) in summaries.items()
                ],
            ]
            run.status, run.ended_at = "success", collected_at
            db.commit()
        except (ValueError, TypeError, AttributeError):
            db.rollback()
            run = db.get(Run, run_id)
            run.logs = [
                {"status": "failed", "message": "全市场恐贪数据获取或校验失败，请重试"}
            ]
            run.status, run.ended_at = "failed", now()
            db.commit()
