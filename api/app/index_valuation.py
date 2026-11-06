"""关联指数估值源解析及按当前历史回看的十日历年因果分位。"""

import bisect
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.collection import now

SOURCE_URL = "https://ai2.jiucaishuo.com/api/index-valuation"
INDEX_CATALOG = {
    "000300.SH": ("沪深300", "000300", ("510300", "510310", "510330", "159919")),
    "000016.SH": ("上证50", "000016", ("510050",)),
    "000010.SH": ("上证180", "000010", ("510180",)),
    "000905.SH": ("中证500", "000905", ("510500", "512500", "159922")),
    "000852.SH": ("中证1000", "000852", ("512100", "159845", "560010", "159629")),
    "399006.SZ": ("创业板指", "399006", ("159915", "159952", "159977", "159205")),
    "000688.SH": ("科创50", "000688", ("588080", "588050")),
    "932000.CSI": ("中证2000", "932000", ("159531",)),
}
METRICS = {
    "pe": ("市盈率", "倍"),
    "pb": ("市净率", "倍"),
    "xilv": ("股息率", "%"),
    "roe": ("净资产收益率", "%"),
    "premium_diff": ("股债风险溢价差值", "百分点"),
}


def source_get(path="", params=None):
    """读取固定公共估值源，有限重试，不向日志传递原始网络异常。"""
    for attempt in range(3):
        try:
            response = httpx.get(
                SOURCE_URL + path,
                params=params,
                timeout=60,
                trust_env=False,
                follow_redirects=False,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.TransportError("源暂时不可用")
            if response.status_code != 200:
                raise ValueError("估值源响应状态无效")
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("估值源响应格式无效")  # noqa: TRY004 — 源格式校验统一使用ValueError
            return body
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("估值源网络请求失败，已重试三次") from None
            time.sleep(attempt + 1)


def parse_history(body, index_code, metric_key):
    """校验单指标完整历史，保留无效原值及缺失，不补造交易日。

    Args:
        body: 源历史JSON。
        index_code: 已配置完整指数代码。
        metric_key: 五类已确认指标之一。

    Returns:
        按日期排序的日期、十进制原值、有效状态三元组。
    """
    if (
        index_code not in INDEX_CATALOG
        or metric_key not in METRICS
        or not isinstance(body, dict)
        or body.get("code") != index_code
        or body.get("metric") != metric_key
    ):
        raise ValueError("估值源指数或指标不匹配")
    series = body.get("series")
    if not isinstance(series, list) or not series:
        raise ValueError("估值源历史为空，保留已有数据")
    rows = {}
    for point in series:
        try:
            day = date.fromisoformat(point["date"])
            raw = point["value"]
            if isinstance(raw, bool):
                raise ValueError("布尔值不是估值")  # noqa: TRY004 — 源格式校验统一使用ValueError
            value = Decimal(str(raw)) if raw is not None else None
            if value is not None and (
                not value.is_finite() or abs(value) >= Decimal("1e16")
            ):
                raise ValueError("估值超出范围")
        except (KeyError, TypeError, InvalidOperation, ValueError):
            raise ValueError("估值日期或数值非法") from None
        if day > now().date() or day in rows:
            raise ValueError("估值日期重复或晚于当前日期")
        status = "missing" if value is None else "valid"
        if value is not None and (
            (metric_key in ("pe", "pb") and value <= 0)
            or (metric_key == "xilv" and value < 0)
        ):
            status = "not_applicable"
        rows[day] = (day, value, status)
    return [rows[day] for day in sorted(rows)]


def rolling_percentiles(rows):
    """以当日为截止，按十日历年有效样本中严格小于当前值的比例计算。

    当前已采历史可能经过修订，结果不代表原历史时点已经发布的数据。
    输入为完整有序历史，显示区间只能在计算后过滤。
    """
    values, result = [], []
    left = 0
    for day, value, status in rows:
        try:
            boundary = day.replace(year=day.year - 10)
        except ValueError:
            boundary = day.replace(year=day.year - 10, day=28)
        while left < len(rows) and rows[left][0] < boundary:
            _, old, old_status = rows[left]
            if old_status == "valid":
                values.pop(bisect.bisect_left(values, old))
            left += 1
        if status != "valid":
            result.append(None)
            continue
        bisect.insort(values, value)
        result.append(100 * bisect.bisect_left(values, value) / len(values))
    return result
