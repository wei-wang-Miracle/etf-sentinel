"""回测数据质量与权益来源：核对交易日、现金分红及复权因子异常。"""

import hashlib
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

import httpx

from app.collection import now

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
            if len(table) < 2:
                raise ValueError("权益分红表缺少数据或明确无事件说明")
            for row in table[1:]:
                if len(row) == 1 and row[0] in ("暂无分红信息!", "暂无分红信息！"):
                    continue
                if len(row) != 5:
                    raise ValueError("权益分红表结构不匹配")
                record, ex, pay = (date.fromisoformat(row[i]) for i in (1, 2, 4))
                match = re.fullmatch(r"每10份派现金([\d.]+)元", row[3])
                if not match or not record <= ex <= pay:
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
            if len(table) < 2:
                raise ValueError("权益折算表缺少数据或明确无事件说明")
            for row in table[1:]:
                if len(row) == 1 and row[0] in ("暂无拆分信息!", "暂无拆分信息！"):
                    continue
                if len(row) != 4:
                    raise ValueError("权益折算表结构不匹配")
                splits.append(
                    {"effective_date": str(date.fromisoformat(row[1])), "ratio": row[3]}
                )
    if found != {"dividends", "splits"}:
        raise ValueError("权益表缺失，无法核实来源")
    if len({e["ex_date"] for e in dividends}) != len(dividends):
        raise ValueError("权益日期重复，拒绝覆盖")
    return {
        "dividends": sorted(dividends, key=lambda e: e["ex_date"]),
        "splits": splits,
    }


def fetch_actions(code):
    """只读抓取支持标的权益页面并返回原始文本与已校验事件。"""
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("ETF代码须为六位数字")
    for attempt in range(3):
        try:
            response = httpx.get(
                SOURCE_TEMPLATE.format(code),
                timeout=30,
                trust_env=False,
                follow_redirects=False,
            )
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.TransportError("权益来源临时服务错误")
            response.raise_for_status()
            actions = parse_actions(response.text)
            return {
                "actions": actions,
                "source_url": SOURCE_TEMPLATE.format(code),
                "source_html": response.text,
                "source_sha256": hashlib.sha256(response.content).hexdigest(),
                "collected_at": now(),
            }
        except httpx.TransportError:
            if attempt == 2:
                raise ValueError("权益来源网络请求失败，已重试三次") from None
            time.sleep(attempt + 1)
        except (httpx.HTTPError, ValueError, ArithmeticError):
            raise ValueError("权益来源暂不可用或结构变化，已有权益保留") from None


def trading_days(start, end):
    """返回上海证券交易日历及依赖版本；不猜测未知年份节假日。"""
    import exchange_calendars as calendars

    calendar = calendars.get_calendar("XSHG")
    try:
        days = [str(t.date()) for t in calendar.sessions_in_range(str(start), str(end))]
    except ValueError:
        raise ValueError("交易日期超出当前日历覆盖，请升级并核实日历") from None
    return days, f"上海交易日历/交易所日历库{calendars.__version__}"


def post_split_rows(rows, splits, interval_start):
    """排除研究区间开始前的折算行情，并从折算后重新预热。

    研究区间内的折算仍由 ``validate_market`` 拒绝；这里只处理已经发生在
    区间开始前的事件，避免把不参与交易的折算前行情送入质量校验。
    """
    prior = [
        event["effective_date"]
        for event in splits
        if event["effective_date"] < str(interval_start)
    ]
    if not prior:
        return rows
    cutoff = max(prior)
    return [row for row in rows if row["trade_date"] > cutoff]


def _decimal_text(value):
    """以非科学计数法保存有限十进制，保持接口数值可复算。"""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _split_multiplier(ratio):
    """将源折算比例转换为每份原份额对应的新份额数。"""
    match = re.fullmatch(r"\s*([\d.]+)\s*[:：]\s*([\d.]+)\s*", str(ratio))
    if not match:
        raise ValueError("份额折算比例格式无效")
    try:
        before, after = (Decimal(value) for value in match.groups())
    except InvalidOperation:
        raise ValueError("份额折算比例格式无效") from None
    if not all(value.is_finite() and value > 0 for value in (before, after)):
        raise ValueError("份额折算比例无效")
    return after / before


def _transition_split_multiplier(splits, previous_date, current_date):
    """返回相邻交易日间已生效折算的累计份额倍率。

    权益来源记录的折算日是登记日，价格在后一个交易日反映；因此将事件匹配
    到 ``previous_date <= effective_date < current_date`` 的交易日窗口。
    """
    multiplier = Decimal(1)
    for split in splits:
        effective_date = split.get("effective_date")
        if previous_date <= effective_date < current_date:
            multiplier *= _split_multiplier(split.get("ratio"))
    return multiplier


def front_adjusted_ohlc_rows(rows):
    """转换为图表用前复权 OHLC，并保持区间末日为真实原始价格。

    ``adjusted_close / close`` 是当前已采集行情可直接核验的复权倍率。以区间
    末日倍率归一后，历史价格会随份额折算保持连续；该序列只用于展示和图表
    均线，不参与任何历史交易决策。
    """
    if not rows:
        return []
    factors = []
    for row in rows:
        adjusted = row.get("adjusted_close")
        if adjusted is None:
            raise ValueError("复权校验字段缺失，无法生成前复权行情")
        close = Decimal(row["close"])
        value = Decimal(adjusted)
        if not all(number.is_finite() and number > 0 for number in (close, value)):
            raise ValueError("复权校验字段或收盘价无效，无法生成前复权行情")
        factors.append(value / close)
    end_factor = factors[-1]
    result = []
    for row, factor in zip(rows, factors, strict=True):
        adjusted = dict(row)
        for key in ("open", "high", "low", "close"):
            adjusted[key] = _decimal_text(Decimal(row[key]) * factor / end_factor)
        result.append(adjusted)
    return result


def indicator_ohlc_rows(rows, actions):
    """转换为顶底等因子使用的因果复权 OHLC 与折算后成交量。

    价格只使用当日 ``adjusted_close / close``，不以未来末日归一；成交量仅按
    已核验份额折算反向换算，避免现金分红的含息复权倍率污染量能指标。
    """
    result = []
    split_factor = Decimal(1)
    splits = actions.get("splits", [])
    for index, row in enumerate(rows):
        if index:
            split_factor *= _transition_split_multiplier(
                splits, rows[index - 1]["trade_date"], row["trade_date"]
            )
        adjusted_close = row.get("adjusted_close")
        if adjusted_close is None:
            raise ValueError("复权校验字段缺失，无法生成因子行情")
        close = Decimal(row["close"])
        factor = Decimal(adjusted_close) / close
        converted = dict(row)
        for key in ("open", "high", "low", "close"):
            converted[key] = _decimal_text(Decimal(row[key]) * factor)
        converted["volume"] = _decimal_text(Decimal(row["volume"]) / split_factor)
        result.append(converted)
    return result


def validate_market(rows, actions, allow_splits=False):
    """阻止缺日、无效价格、未知权益跳变和不支持的份额折算进入回测。

    Raises:
        ValueError: 任一数据质量检查失败；不自动补价或推断现金分红。
    """
    if not rows:
        raise ValueError("暂无日行情")
    days = [r["trade_date"] for r in rows]
    expected, _ = trading_days(days[0], days[-1])
    if days != expected:
        raise ValueError("行情缺少交易日、日期重复或包含非交易日，拒绝回测")
    if not allow_splits and any(
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
            split_multiplier = _transition_split_multiplier(
                actions["splits"], previous["trade_date"], row["trade_date"]
            )
            expected_factor = (
                previous_close / (previous_close - dividend) * split_multiplier
            )
            if abs(observed / expected_factor - 1) > Decimal("0.0004"):
                raise ValueError(
                    f"{row['trade_date']}复权因子与已核实分红不符，拒绝回测"
                )
