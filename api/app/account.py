"""配置内 ETF 实盘持仓与成交同步的纯逻辑。

只处理字段解析、窗口拆分和费用推导，不访问网络或数据库。
"""

from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal

MAX_ROWS = 1000
DEFAULT_WINDOW_DAYS = 30
DEFAULT_SYNC_START = date(2025, 1, 20)
DEFAULT_ACCOUNT_ID = 1


def _code(value) -> str:
    """规范六位证券代码，保留前导零。"""
    return str(value or "").strip().zfill(6)


def _date(value) -> date:
    """解析源日期 YYYYMMDD 或 ISO 日期。"""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError("日期为空")
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"日期格式无效：{text}") from None


def _decimal(value, default=None):
    """把源数字转为 Decimal；缺失时返回默认值。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise TypeError("布尔值不是金额")
    return Decimal(str(value))


def _zero(value) -> Decimal:
    """缺失数字按零处理，用于可空但需要参与计算的源字段。"""
    return _decimal(value, Decimal(0))


def split_windows(
    start: date, end: date, days: int = DEFAULT_WINDOW_DAYS
) -> list[tuple[date, date]]:
    """把闭区间拆成不超过 days 天的连续窗口，窗口之间不重叠。"""
    if days <= 0:
        raise ValueError("窗口天数必须为正")
    if start > end:
        return []
    result = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=days - 1), end)
        result.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return result


def derive_fee(side: str, business_balance, clear_balance) -> Decimal:
    """从成交金额与清算金额差额推导费用；异常方向返回零。"""
    business = _zero(business_balance)
    clear = _zero(clear_balance)
    if str(side) == "1":
        value = clear - business
    elif str(side) == "2":
        value = business - clear
    else:
        return Decimal(0)
    return value if value > 0 else Decimal(0)


def format_source_time(value) -> str | None:
    """把源 9 位 HHMMSSmmm 转为可读时间；非法值返回空。"""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if ":" in text:
        return text
    if not text.isdigit():
        return None
    text = text.zfill(9)
    if len(text) != 9:
        return None
    return f"{text[:2]}:{text[2:4]}:{text[4:6]}.{text[6:]}"


def normalize_holding(row: dict, configured: set[str]) -> dict | None:
    """过滤非配置 ETF，返回只含白名单字段的持仓快照。"""
    code = _code(row.get("STOCK_CODE"))
    if code not in configured:
        return None
    data_date = _date(row.get("DATA_DATE"))
    return {
        "instrument_code": code,
        "data_date": data_date,
        "current_amount": _zero(row.get("CURRENT_AMOUNT")),
        "enable_amount": _zero(row.get("ENABLE_AMOUNT")),
        "frozen_amount": _zero(row.get("FROZEN_AMOUNT")),
        "uncome_buy_amount": _zero(row.get("UNCOME_BUY_AMOUNT")),
        "uncome_sell_amount": _zero(row.get("UNCOME_SELL_AMOUNT")),
        "cost_price": _decimal(row.get("COST_PRICE")),
        "sum_buy_amount": _decimal(row.get("SUM_BUY_AMOUNT")),
        "sum_buy_balance": _decimal(row.get("SUM_BUY_BALANCE")),
        "sum_sell_amount": _decimal(row.get("SUM_SELL_AMOUNT")),
        "sum_sell_balance": _decimal(row.get("SUM_SELL_BALANCE")),
        "source_etl_time": row.get("ETL_TIME"),
    }


def normalize_entrust(row: dict, configured: set[str]) -> dict | None:
    """过滤非配置 ETF，返回委托/成交白名单字段并推导费用。"""
    code = _code(row.get("STOCK_CODE"))
    if code not in configured:
        return None
    missing = [key for key in ("CURR_DATE", "ENTRUST_NO", "ENTRUST_BS") if row.get(key) is None]
    if missing:
        raise ValueError(f"委托关键字段缺失：{','.join(missing)}")
    curr_date = _date(row.get("CURR_DATE"))
    business_amount = _zero(row.get("BUSINESS_AMOUNT"))
    business_balance = _zero(row.get("BUSINESS_BALANCE"))
    clear_balance = _zero(row.get("CLEAR_BALANCE"))
    side = str(row.get("ENTRUST_BS"))
    return {
        "instrument_code": code,
        "curr_date": curr_date,
        "curr_time": None if row.get("CURR_TIME") is None else str(row.get("CURR_TIME")),
        "init_date": _date(row.get("INIT_DATE")) if row.get("INIT_DATE") else None,
        "entrust_no": str(row.get("ENTRUST_NO")),
        "order_id": None if row.get("ORDER_ID") is None else str(row.get("ORDER_ID")),
        "entrust_side": side,
        "entrust_amount": _zero(row.get("ENTRUST_AMOUNT")),
        "entrust_price": _zero(row.get("ENTRUST_PRICE")),
        "entrust_type": None
        if row.get("ENTRUST_TYPE") is None
        else str(row.get("ENTRUST_TYPE")),
        "business_amount": business_amount,
        "business_price": _zero(row.get("BUSINESS_PRICE")),
        "business_balance": business_balance,
        "clear_balance": clear_balance,
        "withdraw_amount": _zero(row.get("WITHDRAW_AMOUNT")),
        "entrust_status": None
        if row.get("ENTRUST_STATUS") is None
        else str(row.get("ENTRUST_STATUS")),
        "fare_kind": None if row.get("FARE_KIND") is None else str(row.get("FARE_KIND")),
        "fee_amount": derive_fee(side, business_balance, clear_balance)
        if business_amount > 0
        else Decimal(0),
        "data_date": _date(row.get("DATA_DATE")) if row.get("DATA_DATE") else curr_date,
        "source_etl_time": row.get("ETL_TIME"),
    }


def _merge_key(row: dict) -> tuple:
    """兼容源字段和规范化字段的去重键。"""
    curr_date = row.get("CURR_DATE", row.get("curr_date"))
    entrust_no = row.get("ENTRUST_NO", row.get("entrust_no"))
    return (str(curr_date), str(entrust_no))


def merge_entrust_rows(rows: Iterable[dict]) -> list[dict]:
    """按委托日期和编号去重，后到的修订覆盖先到的记录。"""
    merged = {}
    for row in rows:
        merged[_merge_key(row)] = row
    return list(merged.values())


def fetch_entrust_window(
    fetch: Callable[[date, date], list[dict]],
    start: date,
    end: date,
    *,
    max_rows: int = MAX_ROWS,
) -> list[dict]:
    """拉取闭区间委托；达到行数上限时按日期二分，避免静默截断。"""
    rows = fetch(start, end)
    if len(rows) < max_rows:
        return rows
    if start >= end:
        raise ValueError("单日委托达到1000行上限，无法完整同步")
    middle = start + timedelta(days=(end - start).days // 2)
    left = fetch_entrust_window(fetch, start, middle, max_rows=max_rows)
    right = fetch_entrust_window(
        fetch, middle + timedelta(days=1), end, max_rows=max_rows
    )
    return merge_entrust_rows([*left, *right])


def sync_start(
    last_date: date | None,
    today: date,
    default_start: date = DEFAULT_SYNC_START,
    overlap_days: int = 7,
) -> date:
    """计算增量起点：首次用默认起点，之后回退重叠天数。"""
    if last_date is None:
        return default_start
    base = min(last_date, today)
    return max(default_start, base - timedelta(days=overlap_days))
