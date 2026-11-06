"""回测数据质量与权益来源：核对交易日、现金分红及复权因子异常。"""

import hashlib
import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

import httpx

from app.collection import now

SUPPORTED_CODES = ("510500", "512100")
SOURCE_TEMPLATE = "https://fundf10.eastmoney.com/fhsp_{}.html"
DATA_VERSION = "1.0"


class ActionTables(HTMLParser):
    """读取源权益表的单元格，忽略页面脚本和其他展示内容。"""

    def __init__(self):
        """初始化表格及单元格解析状态。"""
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        """记录表格、行及单元格边界。"""
        if tag == "table":
            self.table = []
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = ""

    def handle_data(self, data):
        """只保存单元格中的可见文本。"""
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        """结束当前单元格或表格。"""
        if tag in ("td", "th") and self.cell is not None:
            if self.row is not None:
                self.row.append(self.cell.strip())
            self.cell = None
        elif tag == "tr" and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def parse_actions(html):
    """校验权益表结构及日期，将每十份现金转换为每份人民币元。

    Returns:
        dividends和splits；无法识别表格时拒绝把失败当成无分红。

    Raises:
        ValueError: 权益结构、金额、重复事件或日期顺序不合法。
    """
    parser = ActionTables()
    parser.feed(html)
    dividends, splits = [], []
    found = set()
    for table in parser.tables:
        if not table or not table[0]:
            continue
        if "权益登记日" in table[0]:
            found.add("dividends")
            for row in table[1:]:
                if len(row) != 5:
                    raise ValueError("权益分红表结构不匹配")
                record, ex, pay = (date.fromisoformat(row[i]) for i in (1, 2, 4))
                match = re.fullmatch(r"每10份派现金([\d.]+)元", row[3])
                if not match or not record < ex <= pay:
                    raise ValueError("权益日期或分红单位不符合预期")
                cash = Decimal(match[1]) / 10
                if not cash.is_finite() or cash <= 0:
                    raise ValueError("权益分红金额无效")
                dividends.append(
                    {
                        "record_date": str(record),
                        "ex_date": str(ex),
                        "pay_date": str(pay),
                        "cash_per_share": str(cash),
                    }
                )
        elif "拆分折算日" in table[0]:
            found.add("splits")
            for row in table[1:]:
                if len(row) != 4:
                    raise ValueError("权益折算表结构不匹配")
                splits.append(
                    {"effective_date": str(date.fromisoformat(row[1])), "ratio": row[3]}
                )
    if found != {"dividends", "splits"} or not dividends:
        raise ValueError("权益表缺失或无有效分红，无法核实来源")
    if len({e["ex_date"] for e in dividends}) != len(dividends):
        raise ValueError("权益日期重复，拒绝覆盖")
    return {
        "dividends": sorted(dividends, key=lambda e: e["ex_date"]),
        "splits": splits,
    }


def fetch_actions(code):
    """只读抓取支持标的权益页面并返回原始文本与已校验事件。"""
    if code not in SUPPORTED_CODES:
        raise ValueError("本版仅核实510500和512100权益")
    try:
        response = httpx.get(
            SOURCE_TEMPLATE.format(code),
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        )
        response.raise_for_status()
        actions = parse_actions(response.text)
    except (httpx.HTTPError, ValueError, ArithmeticError):
        raise ValueError("权益来源暂不可用或结构变化，已有权益保留") from None
    return {
        "actions": actions,
        "source_url": SOURCE_TEMPLATE.format(code),
        "source_html": response.text,
        "source_sha256": hashlib.sha256(response.content).hexdigest(),
        "collected_at": now(),
    }


def trading_days(start, end):
    """返回上海证券交易日历及依赖版本；不猜测未知年份节假日。"""
    import exchange_calendars as calendars

    calendar = calendars.get_calendar("XSHG")
    try:
        days = [str(t.date()) for t in calendar.sessions_in_range(str(start), str(end))]
    except ValueError:
        raise ValueError("交易日期超出当前日历覆盖，请升级并核实日历") from None
    return days, f"上海交易日历/交易所日历库{calendars.__version__}"


def validate_market(rows, actions):
    """阻止缺日、无效价格、未知权益跳变和区间内份额折算进入回测。

    Raises:
        ValueError: 任一数据质量检查失败；不自动补价或推断现金分红。
    """
    if not rows:
        raise ValueError("暂无日行情")
    days = [r["trade_date"] for r in rows]
    expected, _ = trading_days(days[0], days[-1])
    if days != expected:
        raise ValueError("行情缺少交易日、日期重复或包含非交易日，拒绝回测")
    if any(
        days[0] <= event["effective_date"] <= days[-1] for event in actions["splits"]
    ):
        raise ValueError("区间包含份额折算，本版尚不支持，拒绝回测")
    dividends = {
        e["ex_date"]: Decimal(e["cash_per_share"]) for e in actions["dividends"]
    }
    for i, row in enumerate(rows):
        op, high, low, close = [
            Decimal(row[k]) for k in ("open", "high", "low", "close")
        ]
        adjusted = (
            Decimal(row["adjusted_close"])
            if row["adjusted_close"] is not None
            else Decimal(0)
        )
        if (
            not all(v.is_finite() and v > 0 for v in (op, high, low, close, adjusted))
            or not low <= min(op, close) <= max(op, close) <= high
        ):
            raise ValueError("行情或复权校验字段缺失或价格关系非法")
        volume = Decimal(row["volume"])
        if not volume.is_finite() or volume <= 0:
            raise ValueError(
                "存在零成交量或无效成交量；缺少事前可知停牌资料，本版拒绝回测"
            )
        if i:
            previous = rows[i - 1]
            previous_close = Decimal(previous["close"])
            observed = (adjusted / close) / (
                Decimal(previous["adjusted_close"]) / previous_close
            )
            dividend = dividends.get(row["trade_date"], Decimal(0))
            if dividend >= previous_close:
                raise ValueError("权益金额超过前收盘价")
            expected_factor = previous_close / (previous_close - dividend)
            if abs(observed / expected_factor - 1) > Decimal("0.0004"):
                raise ValueError(
                    f"{row['trade_date']}复权因子与已核实分红不符，拒绝回测"
                )
