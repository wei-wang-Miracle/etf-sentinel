"""FundDB ETF 档案目录与详情的受控读取和响应解析。"""
# ruff: noqa: TRY004

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

CATALOG_URL = "https://ai2.jiucaishuo.com/api/fundsale/etf"
DETAIL_URL = "https://ai2.jiucaishuo.com/api/fund/detail"
CATALOG_SOURCE_URL = CATALOG_URL
CATALOG_PAGE_SIZE = 200
CATALOG_CACHE_TTL = timedelta(minutes=30)

_cache_lock = threading.Lock()
_catalog_cache: tuple[datetime, list[dict[str, Any]]] | None = None
_preview_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


def cache_preview_profile(code: str, profile: dict[str, Any]) -> None:
    """短期缓存预览到的ETF档案，供随后的确认新增直接复用而不再阻塞外部网络。"""
    now_at = datetime.now().astimezone()
    with _cache_lock:
        _preview_cache[code] = (now_at, dict(profile))


def pop_cached_preview_profile(code: str) -> dict[str, Any] | None:
    """取出仍在有效期内的预览档案缓存，过期或不存在返回空。"""
    now_at = datetime.now().astimezone()
    with _cache_lock:
        entry = _preview_cache.pop(code, None)
    if entry is None or now_at - entry[0] >= CATALOG_CACHE_TTL:
        return None
    return entry[1]


def _text(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field}不能为空")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field}格式非法")
    normalized = value.strip()
    if not normalized:
        if required:
            raise ValueError(f"{field}不能为空")
        return None
    return normalized


def _decimal(
    value: object,
    field: str,
    *,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    nullable: bool = True,
) -> Decimal | None:
    if value is None or value == "" or (
        isinstance(value, str) and value.strip() in {"-", "--", "—"}
    ):
        if nullable:
            return None
        raise ValueError(f"{field}不能为空")
    if isinstance(value, bool):
        raise ValueError(f"{field}格式非法")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}格式非法") from exc
    if not number.is_finite():
        raise ValueError(f"{field}必须是有限数值")
    if minimum is not None and number < minimum:
        raise ValueError(f"{field}不能小于{minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{field}不能大于{maximum}")
    return number


def _date(value: object, field: str, current_date: date) -> date | None:
    text = _text(value, field)
    if text is None:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}格式非法") from exc
    if parsed > current_date:
        raise ValueError(f"{field}晚于当前日期")
    return parsed


def _catalog_items(body: object) -> tuple[list[object], int]:
    if isinstance(body, list):
        return body, len(body)
    if not isinstance(body, dict):
        raise ValueError("ETF目录响应格式非法")
    data = body.get("data")
    if not isinstance(data, dict):
        raise ValueError("ETF目录响应缺少data")
    items = data.get("lists")
    total = data.get("total")
    if not isinstance(items, list) or isinstance(total, bool):
        raise ValueError("ETF目录列表或总数格式非法")
    try:
        normalized_total = int(total)
    except (ValueError, TypeError) as exc:
        raise ValueError("ETF目录总数格式非法") from exc
    if normalized_total < len(items):
        raise ValueError("ETF目录总数小于当前页记录数")
    return items, normalized_total


def parse_catalog_page(body: object, current_date: date) -> tuple[list[dict[str, Any]], int]:
    """解析单页目录；所有日期和数值均以采集当天为校验边界。"""
    items, total = _catalog_items(body)
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("ETF目录记录格式非法")
        code = _text(item.get("fund_int_code"), "证券代码", required=True)
        if code is None or len(code) != 6 or not code.isdigit():
            raise ValueError("证券代码必须为六位数字")
        if code in seen_codes:
            raise ValueError("ETF目录页存在重复证券代码")
        seen_codes.add(code)

        flow_date = _date(item.get("guimo_date"), "份额日期", current_date)
        discount = _decimal(
            item.get("t-1_deal")
            if item.get("t-1_deal") not in (None, "")
            else item.get("diff_deal_price"),
            "折溢价率",
        )
        rows.append(
            {
                "instrument_code": code,
                "fund_name": _text(item.get("fund_name"), "基金简称"),
                "fund_full_name": _text(item.get("_fullname"), "基金全称"),
                "category_primary": _text(item.get("category_0"), "一级分类"),
                "category_tag": _text(item.get("category_1"), "二级分类"),
                "tracking_index_code": _text(
                    item.get("gaikuang_genzongcode"), "跟踪指数代码"
                ),
                "tracking_index_name": _text(
                    item.get("gaikuang_genzongzhishu"), "跟踪指数名称"
                ),
                "setup_date": _date(item.get("setup_date"), "成立日期", current_date),
                "management_fee_pct": _decimal(item.get("feilv_guanlifei"), "管理费率"),
                "custody_fee_pct": _decimal(item.get("feilv_tuoguanfei"), "托管费率"),
                "linked_otc_code": _text(item.get("lianjie_code"), "联接基金代码"),
                "source_url": CATALOG_SOURCE_URL,
                "flow": (
                    {
                        "trade_date": flow_date,
                        "unit_shares_100m": _decimal(
                            item.get("guimo_zuixin_fene"), "最新份额"
                        ),
                        "aum_100m": _decimal(
                            item.get("guimo_zuixin_guimo"), "最新规模"
                        ),
                        "net_share_flow_7d_100m": _decimal(
                            item.get("guimo_fene_7"), "近7日份额变动"
                        ),
                        "net_share_flow_30d_100m": _decimal(
                            item.get("guimo_fene_30"), "近30日份额变动"
                        ),
                        "discount_premium_pct": discount,
                        "purchase_status": _text(item.get("sg_status"), "申购状态"),
                        "redeem_status": _text(item.get("sh_status"), "赎回状态"),
                    }
                    if flow_date is not None
                    else None
                ),
            }
        )
    return rows, total


def parse_fund_detail(
    body: object, tracking_index_code: str | None
) -> dict[str, Decimal | str | None]:
    """从基金详情中提取已建议指数的相关度，不把相关度当作映射证据。"""
    if not isinstance(body, dict) or not isinstance(body.get("data"), dict):
        raise ValueError("ETF详情响应格式非法")
    code = _text(tracking_index_code, "跟踪指数代码")
    if code is None:
        return {"tracking_index_code": None, "index_corr": None}
    candidates = body["data"].get("index_corr")
    if candidates is None:
        return {"tracking_index_code": code, "index_corr": None}
    if not isinstance(candidates, list):
        raise ValueError("ETF详情指数相关度格式非法")
    matching = [item for item in candidates if isinstance(item, dict) and item.get("code") == code]
    if not matching:
        return {"tracking_index_code": code, "index_corr": None}
    value = _decimal(
        matching[0].get("corr"),
        "指数相关度",
        minimum=Decimal(0),
        maximum=Decimal(1),
        nullable=False,
    )
    return {"tracking_index_code": code, "index_corr": value}


def fetch_catalog_page(page: int, *, client: httpx.Client | None = None) -> object:
    """读取 FundDB ETF 目录的一页，不记录或暴露外部请求细节。"""
    if page < 1:
        raise ValueError("页码必须从1开始")
    session = client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
    owns_client = client is None
    try:
        response = session.post(
            CATALOG_URL,
            json={"etf_id": 2, "type": "pc", "page": page, "page_size": CATALOG_PAGE_SIZE},
        )
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            session.close()


def fetch_catalog(*, current_date: date | None = None) -> list[dict[str, Any]]:
    """读取完整目录并短暂缓存，避免新增预览与日任务重复拉取全量列表。"""
    global _catalog_cache
    captured_at = datetime.now().astimezone()
    with _cache_lock:
        if _catalog_cache and captured_at - _catalog_cache[0] < CATALOG_CACHE_TTL:
            return _catalog_cache[1]
    today = current_date or captured_at.date()
    collected: list[dict[str, Any]] = []
    expected_total: int | None = None
    page = 1
    while expected_total is None or len(collected) < expected_total:
        rows, total = parse_catalog_page(fetch_catalog_page(page), today)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise ValueError("ETF目录分页总数不一致")
        if not rows:
            raise ValueError("ETF目录提前结束")
        collected.extend(rows)
        page += 1
    if len(collected) != expected_total:
        raise ValueError("ETF目录记录数与总数不一致")
    codes = [row["instrument_code"] for row in collected]
    if len(codes) != len(set(codes)):
        raise ValueError("ETF目录跨页存在重复证券代码")
    with _cache_lock:
        _catalog_cache = (captured_at, collected)
    return collected


def fetch_fund_detail(code: str, *, client: httpx.Client | None = None) -> object:
    """读取单只 ETF 详情，仅供档案相关度和预览使用。"""
    if len(code) != 6 or not code.isdigit():
        raise ValueError("证券代码必须为六位数字")
    session = client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)
    owns_client = client is None
    try:
        response = session.get(DETAIL_URL, params={"fund_code": code})
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            session.close()
