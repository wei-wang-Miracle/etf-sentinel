"""分级免费历史日行情采集与跨源对比验证，保证上市以来行情可用且正确。"""

import re
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.backtest_data import (
    _transition_split_multiplier,
    expected_transition_factors,
    trading_days,
)

# 分级顺序：优先东财（全历史、含成交额、与权益同源），备用新浪（精度一致），兜底腾讯（全历史分段）
SOURCE_TIERS = ("eastmoney", "sina", "tencent")
# 免费历史源允许的最早日；交易所日历实际覆盖起点由运行时依赖决定
MIN_CALENDAR_DATE = date(2006, 11, 27)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}
_EASTMONEY_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_SINA_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
_TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def audited_suspensions(source_series):
    """列出共同覆盖区间内所有可用源均无交易的交易日，供冻结严格放行。"""
    available = {
        name: rows
        for name, rows in source_series.items()
        if rows
    }
    if not available:
        return {
            "available_source_count": 0,
            "sources": [],
            "calendar_version": None,
            "verified_suspensions": [],
        }
    source_dates = {
        name: {row["trade_date"] for row in rows}
        for name, rows in available.items()
    }
    common_start = max(max(min(days) for days in source_dates.values()), str(MIN_CALENDAR_DATE))
    common_end = min(max(days) for days in source_dates.values())
    # 最早一根免费历史可能早于交易日历依赖的首个 session。该日保留为行情
    # 来源边界，但不对没有日历证据的区间推断停牌。
    import exchange_calendars as calendars

    calendar = calendars.get_calendar("XSHG")
    audit_start = max(common_start, str(calendar.first_session.date()))
    expected, calendar_version = trading_days(audit_start, common_end)
    all_observed = set().union(*source_dates.values())
    sources = sorted(available)
    return {
        "available_source_count": len(sources),
        "sources": sources,
        "calendar_version": calendar_version,
        "verified_suspensions": [
            {"trade_date": day, "sources": sources}
            for day in expected
            if day not in all_observed
        ],
    }


def market_codes(code):
    """将六位 ETF 代码转换为各数据源所需的交易所前缀。

    功能：根据证券代码首位判断沪深市场并校验格式。
    参数：code (str) - 六位字符串形式的证券代码。
    返回：tuple[str, str] - 分别为新浪/腾讯前缀（sh/sz）与东财市场编号（1/0）。
    """
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        raise ValueError("ETF代码须为六位数字")
    if code.startswith(("5", "6", "9")):
        return "sh", "1"
    if code.startswith(("0", "1", "2", "3")):
        return "sz", "0"
    raise ValueError(f"暂不支持识别市场的代码前缀：{code}")


def _to_decimal(raw, label):
    """安全转换有限十进制数值，拒绝 NaN 或无穷大。"""
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label}不是有效数字") from None
    if not value.is_finite():
        raise ValueError(f"{label}不是有限数字")
    return value


def _normalize_row(
    *,
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    amount=None,
    change_pct=None,
    end_date=None,
):
    """校验单日不复权 OHLCV 约束并统一字段格式。

    功能：确保高低价关系合法、成交量非负且日期未越界。
    参数：各行情字段及可选截止日期 end_date。
    返回：dict - 标准化后的单日行情字典（成交量统一为份）。
    """
    day = date.fromisoformat(str(trade_date))
    if end_date is not None and day > end_date:
        return None
    op = _to_decimal(open_price, "开盘价")
    hi = _to_decimal(high_price, "最高价")
    lo = _to_decimal(low_price, "最低价")
    cl = _to_decimal(close_price, "收盘价")
    vol = _to_decimal(volume, "成交量")
    if any(v <= 0 for v in (op, hi, lo, cl)) or vol < 0:
        raise ValueError(f"{day} 价格或成交量非正/为负")
    if not lo <= min(op, cl) <= max(op, cl) <= hi:
        raise ValueError(f"{day} 最高最低价关系错误")
    amt = _to_decimal(amount, "成交额") if amount is not None else None
    if amt is not None and amt < 0:
        raise ValueError(f"{day} 成交额为负")
    chg = _to_decimal(change_pct, "涨跌幅") if change_pct is not None else None
    return {
        "trade_date": str(day),
        "open": op,
        "high": hi,
        "low": lo,
        "close": cl,
        "volume": vol,
        "amount": amt,
        "change_pct": chg,
    }


def _request_json(client, url, params, *, attempts=3):
    """执行带有限退避重试的只读 HTTP GET 请求。"""
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params, headers=_HEADERS)
            if response.status_code in (429, 500, 502, 503, 504):
                raise httpx.TransportError(f"HTTP {response.status_code}")
            if response.status_code != 200:
                raise ValueError(f"HTTP {response.status_code}")
            return response.json()
        except httpx.TransportError as exc:
            if attempt == attempts - 1:
                raise ValueError(f"网络请求失败，已重试{attempts}次：{exc}") from None
            time.sleep(0.8 * (attempt + 1))
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            if isinstance(exc, ValueError):
                raise
            raise ValueError(f"响应解析失败：{exc}") from None


def _finalize_series(rows, source_name):
    """按交易日期升序整理并检查重复交易日。"""
    seen = {}
    for row in rows:
        if row is None:
            continue
        day = row["trade_date"]
        if day in seen:
            raise ValueError(f"{source_name} 返回重复交易日：{day}")
        seen[day] = row
    if not seen:
        raise ValueError(f"{source_name} 未返回任何有效历史行情")
    return [seen[day] for day in sorted(seen)]


def fetch_eastmoney_history(code, *, end_date=None, client=None):
    """优先源：抓取东方财富自上市以来的不复权日线（含成交额）。

    功能：从东财公开 K 线接口拉取 fqt=0 全历史，成交量由手换算为份。
    参数：code (str) - ETF 代码；end_date (date|None) - 截止日期；client - 可选 httpx 客户端。
    返回：list[dict] - 按日期升序排列的标准日行情列表。
    """
    _, em_market = market_codes(code)
    own_client = client is None
    session = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
    try:
        payload = _request_json(
            session,
            _EASTMONEY_URL,
            {
                "secid": f"{em_market}.{code}",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",
                "fqt": "0",
                "beg": "19900101",
                "end": end_date.strftime("%Y%m%d") if end_date else "20991231",
            },
        )
    finally:
        if own_client:
            session.close()

    data = payload.get("data") if isinstance(payload, dict) else None
    klines = (data or {}).get("klines") if isinstance(data, dict) else None
    if not isinstance(klines, list) or not klines:
        raise ValueError("东财未返回 klines 行情数据")

    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 9:
            raise ValueError("东财 kline 字段数量不足")
        # 东财 f56 为手（100份），乘以 100 对齐本地数据库的份口径
        rows.append(
            _normalize_row(
                trade_date=parts[0],
                open_price=parts[1],
                close_price=parts[2],
                high_price=parts[3],
                low_price=parts[4],
                volume=_to_decimal(parts[5], "东财成交量") * 100,
                amount=parts[6],
                change_pct=parts[8],
                end_date=end_date,
            )
        )
    return _finalize_series(rows, "eastmoney")


def fetch_sina_history(code, *, end_date=None, client=None, datalen=5000):
    """备用源：抓取新浪财经不复权日线（精度三位小数，成交量为份）。

    功能：作为高精度、无早期拆分布局误差的备用历史行情源。
    参数：code (str) - ETF 代码；end_date (date|None) - 截止日期；datalen - 最大条数。
    返回：list[dict] - 按日期升序排列的标准日行情列表（成交额为空）。
    """
    prefix, _ = market_codes(code)
    own_client = client is None
    session = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
    try:
        payload = _request_json(
            session,
            _SINA_URL,
            {
                "symbol": f"{prefix}{code}",
                "scale": "240",
                "ma": "no",
                "datalen": str(datalen),
            },
        )
    finally:
        if own_client:
            session.close()

    if not isinstance(payload, list) or not payload:
        raise ValueError("新浪未返回日线数组")

    rows = [
        _normalize_row(
            trade_date=item["day"],
            open_price=item["open"],
            high_price=item["high"],
            low_price=item["low"],
            close_price=item["close"],
            volume=item["volume"],
            amount=None,
            end_date=end_date,
        )
        for item in payload
    ]
    return _finalize_series(rows, "sina")


def fetch_tencent_history(
    code, *, end_date=None, client=None, start_year=2004
):
    """兜底源：按两年分段抓取腾讯财经不复权日线，突破单次条数限制直达上市日。

    功能：当东财不可用且新浪超过条数上限或存在早期缺口时提供上市以来兜底与交叉核对。
    参数：code (str) - ETF 代码；end_date (date|None) - 截止日期；start_year - 起始分段年份。
    返回：list[dict] - 按日期升序排列的标准日行情列表（成交额为空）。
    """
    prefix, _ = market_codes(code)
    symbol = f"{prefix}{code}"
    last_year = end_date.year if end_date else date.today().year
    own_client = client is None
    session = client or httpx.Client(timeout=20, trust_env=False, follow_redirects=False)
    merged = {}
    try:
        for year in range(start_year, last_year + 1, 2):
            chunk_end = min(year + 1, last_year)
            payload = _request_json(
                session,
                _TENCENT_URL,
                {
                    "param": f"{symbol},day,{year}-01-01,{chunk_end}-12-31,640,",
                },
            )
            data = (payload.get("data") or {}).get(symbol) if isinstance(payload, dict) else None
            days = (data or {}).get("day") if isinstance(data, dict) else None
            if not isinstance(days, list):
                continue
            for item in days:
                if not isinstance(item, list) or len(item) < 6:
                    raise ValueError("腾讯日线记录格式异常")
                normalized = _normalize_row(
                    trade_date=item[0],
                    open_price=item[1],
                    close_price=item[2],
                    high_price=item[3],
                    low_price=item[4],
                    volume=_to_decimal(item[5], "腾讯成交量") * 100,
                    amount=None,
                    end_date=end_date,
                )
                if normalized is not None:
                    merged[normalized["trade_date"]] = normalized
    finally:
        if own_client:
            session.close()

    if not merged:
        raise ValueError("腾讯未返回任何日线数据")
    return [merged[day] for day in sorted(merged)]


_FETCHERS = {
    "eastmoney": fetch_eastmoney_history,
    "sina": fetch_sina_history,
    "tencent": fetch_tencent_history,
}


def _max_price_diff(row_a, row_b):
    """计算两条日行情 OHLC 四价的最大绝对差。"""
    return max(
        abs(row_a[key] - row_b[key]) for key in ("open", "high", "low", "close")
    )


def _volume_matches(vol_a, vol_b):
    """校验成交量一致性，兼容按手取整导致的百份以内舍入差。"""
    diff = abs(vol_a - vol_b)
    if diff <= Decimal(200):
        return True
    base = max(vol_a, vol_b, Decimal(1))
    return diff / base <= Decimal("0.01")


def _check_local_overlap(candidate_rows, existing_rows):
    """用本地已入库金标准行情校验免费源重叠区间。

    功能：核对价格逐日精确一致、成交量单位及数量一致、成交额（如双方均有）一致。
    参数：candidate_rows - 候选免费源行情；existing_rows - 本地数据库已有行情。
    返回：dict - 核对结果摘要，含是否通过、重叠天数及不匹配详情。
    """
    if not existing_rows:
        return {"checked": False, "overlap_days": 0, "passed": True, "issues": []}

    by_date = {row["trade_date"]: row for row in candidate_rows}
    missing = []
    price_mismatches = []
    volume_mismatches = []
    amount_mismatches = []

    for local in existing_rows:
        day = str(local["trade_date"])
        remote = by_date.get(day)
        if remote is None:
            missing.append(day)
            continue
        local_norm = {
            "open": Decimal(str(local["open"])),
            "high": Decimal(str(local["high"])),
            "low": Decimal(str(local["low"])),
            "close": Decimal(str(local["close"])),
        }
        diff = _max_price_diff(remote, local_norm)
        if diff > Decimal("0.0001"):
            price_mismatches.append({"date": day, "max_diff": str(diff)})
        if not _volume_matches(remote["volume"], Decimal(str(local["volume"]))):
            volume_mismatches.append(
                {
                    "date": day,
                    "remote": str(remote["volume"]),
                    "local": str(local["volume"]),
                }
            )
        if remote.get("amount") is not None and local.get("amount") is not None:
            local_amt = Decimal(str(local["amount"]))
            amt_diff = abs(remote["amount"] - local_amt)
            if amt_diff > Decimal(100) and amt_diff / max(local_amt, Decimal(1)) > Decimal("0.001"):
                amount_mismatches.append(
                    {
                        "date": day,
                        "remote": str(remote["amount"]),
                        "local": str(local_amt),
                    }
                )

    issues = []
    if missing:
        issues.append(f"缺少本地已有交易日 {len(missing)} 天（首日 {missing[0]}）")
    if price_mismatches:
        issues.append(f"重叠期 OHLC 价格不一致 {len(price_mismatches)} 天")
    if volume_mismatches:
        issues.append(f"重叠期成交量不一致 {len(volume_mismatches)} 天")
    if amount_mismatches:
        issues.append(f"重叠期成交额不一致 {len(amount_mismatches)} 天")

    return {
        "checked": True,
        "overlap_days": len(existing_rows),
        "passed": not issues,
        "missing_dates": missing[:10],
        "price_mismatches": price_mismatches[:5],
        "volume_mismatches": volume_mismatches[:5],
        "amount_mismatches": amount_mismatches[:5],
        "issues": issues,
    }


def _cross_compare_peers(primary_name, primary_rows, peer_series):
    """在多个可用免费源之间做全历史横向对比，并利用三方表决消解单源历史瑕疵。

    功能：对比共同交易日价格、成交量与日期覆盖，识别单源早期畸变或遗漏。
    参数：
        primary_name (str) - 当前拟选用的主数据源名称。
        primary_rows (list[dict]) - 主数据源行列表。
        peer_series (dict[str, list[dict]]) - 其他可用免费源的行情映射。
    返回：dict - 跨源对比审计报告，包含 passed、分歧详情与被三方表决排除的单项异常。
    """
    if not peer_series:
        return {
            "checked": False,
            "peer_count": 0,
            "passed": False,
            "issues": ["无其他可用免费源可供横向核对"],
            "peers": {},
        }

    primary_map = {row["trade_date"]: row for row in primary_rows}
    peer_maps = {
        name: {row["trade_date"]: row for row in rows}
        for name, rows in peer_series.items()
    }
    peer_reports = {}
    hard_conflicts = []
    soft_warnings = []

    for peer_name, peer_map in peer_maps.items():
        common_dates = sorted(set(primary_map) & set(peer_map))
        peer_only = sorted(set(peer_map) - set(primary_map))
        # 只统计落在对方覆盖区间的缺失日期（新浪受 5000 根上限截断更早日期不记为异常）
        peer_start = min(peer_map)
        primary_only_in_span = sorted(
            d for d in (set(primary_map) - set(peer_map)) if d >= peer_start
        )

        gt_1tick = []
        severe_diffs = []
        for day in common_dates:
            diff = _max_price_diff(primary_map[day], peer_map[day])
            if diff > Decimal("0.001"):
                rel = diff / max(primary_map[day]["close"], Decimal("0.001"))
                item = {
                    "date": day,
                    "diff": str(diff),
                    "rel": str(round(rel, 6)),
                    "primary_close": str(primary_map[day]["close"]),
                    "peer_close": str(peer_map[day]["close"]),
                }
                gt_1tick.append(item)
                if diff > Decimal("0.005") and rel > Decimal("0.003"):
                    severe_diffs.append(item)

        # 如果存在第三源，检查严重分歧或单边缺失是否能被另外两源一致否决
        unresolved_severe = []
        resolved_by_consensus = []
        other_maps = {k: v for k, v in peer_maps.items() if k != peer_name}
        for item in severe_diffs:
            day = item["date"]
            confirmed_primary = any(
                day in m and _max_price_diff(primary_map[day], m[day]) <= Decimal("0.003")
                for m in other_maps.values()
            )
            if confirmed_primary:
                resolved_by_consensus.append(item)
            else:
                unresolved_severe.append(item)

        unresolved_missing = []
        for day in peer_only:
            # 只有其他源同样不存在该日、或无法证实为坏数据时才算主源漏采
            confirmed_by_third = any(day in m for m in other_maps.values())
            if confirmed_by_third or not other_maps:
                unresolved_missing.append(day)

        peer_reports[peer_name] = {
            "common_days": len(common_dates),
            "gt_1tick_count": len(gt_1tick),
            "severe_diff_count": len(severe_diffs),
            "resolved_by_consensus_count": len(resolved_by_consensus),
            "unresolved_severe": unresolved_severe[:10],
            "primary_missing_dates": peer_only[:10],
            "peer_missing_in_span": primary_only_in_span[:10],
        }
        if unresolved_severe:
            hard_conflicts.append(
                f"与 {peer_name} 存在未消解价格大幅分歧 {len(unresolved_severe)} 天"
            )
        if unresolved_missing:
            hard_conflicts.append(
                f"{primary_name} 相比 {peer_name} 缺失交易日 {len(unresolved_missing)} 天"
            )
        if resolved_by_consensus:
            soft_warnings.append(
                f"{peer_name} 有 {len(resolved_by_consensus)} 天历史分歧已被三源多数一致否决"
            )
        if primary_only_in_span:
            soft_warnings.append(
                f"{peer_name} 在其时间段内缺少 {len(primary_only_in_span)} 个交易日（主源完整）"
            )

    return {
        "checked": True,
        "peer_count": len(peer_series),
        "passed": not hard_conflicts,
        "issues": hard_conflicts,
        "warnings": soft_warnings,
        "peers": peer_reports,
    }


def collect_and_verify_history(
    code,
    *,
    end_date=None,
    existing_rows=(),
    fetchers=None,
    require_independent_check=True,
    tencent_start_year=2004,
):
    """按 优先 -> 备用 -> 兜底 拉取上市以来行情，并在可用前提下执行多源对比验证。

    功能：确保数据源挂掉时自动降级，且入库前必须经过可用源对比与本地重叠校准。
    参数：
        code (str) - 六位 ETF 代码。
        end_date (date|None) - 允许的最大源交易日期。
        existing_rows (Sequence[dict]) - 本地已有行情（作为重叠校准锚）。
        fetchers (dict|None) - 可注入自定义源函数用于测试。
        require_independent_check (bool) - 是否要求至少具备本地锚或两家免费源交叉确认。
        tencent_start_year (int) - 腾讯分段拉取起始年份，增量降级时可只拉近年窗口。
    返回：dict - 含 selected_source、rows、source_status、overlap_check 与 cross_check。
    """
    active_fetchers = fetchers or _FETCHERS
    fetched = {}
    source_status = {}

    for tier_name in SOURCE_TIERS:
        fetcher = active_fetchers.get(tier_name)
        if fetcher is None:
            source_status[tier_name] = {"available": False, "reason": "未配置抓取器"}
            continue
        try:
            if tier_name == "tencent" and fetchers is None:
                rows = fetcher(code, end_date=end_date, start_year=tencent_start_year)
            else:
                rows = fetcher(code, end_date=end_date)
            if not rows:
                raise ValueError("返回空序列")
            fetched[tier_name] = rows
            source_status[tier_name] = {
                "available": True,
                "count": len(rows),
                "start": rows[0]["trade_date"],
                "end": rows[-1]["trade_date"],
                "has_amount": any(r["amount"] is not None for r in rows),
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            source_status[tier_name] = {"available": False, "reason": str(exc)}

    if not fetched:
        raise ValueError(f"{code} 三级免费历史行情源全部不可用：{source_status}")

    # 逐级尝试挑选“既通过本地重叠锚校验、又通过可用源横向对比”的最高优先级源
    rejection_reasons = []
    for candidate_name in SOURCE_TIERS:
        if candidate_name not in fetched:
            continue
        candidate_rows = fetched[candidate_name]
        overlap = _check_local_overlap(candidate_rows, existing_rows)
        if not overlap["passed"]:
            rejection_reasons.append(f"{candidate_name}未通过本地锚比对：{overlap['issues']}")
            continue

        peers = {k: v for k, v in fetched.items() if k != candidate_name}
        cross = _cross_compare_peers(candidate_name, candidate_rows, peers)
        if peers and not cross["passed"]:
            rejection_reasons.append(f"{candidate_name}未通过横向源对比：{cross['issues']}")
            continue

        # 可用性前提下的独立验证门槛：至少有“本地锚”或“可用横向对照源”之一
        has_independent_evidence = bool(existing_rows) or bool(peers)
        if require_independent_check and not has_independent_evidence:
            rejection_reasons.append(
                f"{candidate_name} 缺少第二可用源且无本地重叠锚，拒绝孤立入库"
            )
            continue

        cross["suspension_audit"] = audited_suspensions(fetched)

        return {
            "code": code,
            "selected_source": candidate_name,
            "rows": candidate_rows,
            "source_status": source_status,
            "overlap_check": overlap,
            "cross_check": cross,
            "rejected_tiers": rejection_reasons,
        }

    raise ValueError(
        f"{code} 所有可用免费历史行情源均未通过一致性对比验证：{'；'.join(rejection_reasons)}"
    )


def compute_historical_adjusted_close(
    rows,
    actions,
    *,
    anchor_date=None,
    anchor_factor=Decimal(1),
    observed_transitions=None,
    known_factors=None,
):
    """基于本地锚定复权倍率与已核验分红折算事件，向历史反推连续的 adjusted_close。

    功能：保持回补历史行与库内已有 ChatBI 复权收盘在接缝日连续无跳变，
          并严格对齐 backtest_data.validate_market 的复权比率定义。
    参数：
        rows (list[dict]) - 升序全历史不复权行情（需含 close）。
        actions (dict) - BacktestSource 中的 dividends 与 splits。
        anchor_date (str|None) - 锚定日期（通常为本地库已有最早交易日）；为空则锚定末日为 1。
        anchor_factor (Decimal) - 锚定日当日的 adjusted_close / close 倍率。
        observed_transitions (dict|None) - 可选 {(prev_day, curr_day): observed_ratio}，
            用于在同日拆股+分红时匹配本地已核验数据源实际采用的除权顺序。
        known_factors (dict|None) - 可选 {trade_date: factor}，用于在向前后推算时锚定已知接缝倍率，避免跨多年累积误差。
    返回：list[Decimal] - 与 rows 等长的复权收盘价序列。
    """
    if not rows:
        return []
    dates = [row["trade_date"] for row in rows]
    target_date = anchor_date or dates[-1]
    if target_date not in dates:
        raise ValueError(f"锚定日期 {target_date} 不在历史行情序列中")
    anchor_index = dates.index(target_date)

    dividends = {
        event["ex_date"]: Decimal(str(event["cash_per_share"]))
        for event in actions.get("dividends", [])
    }
    splits = actions.get("splits", [])
    observed_map = observed_transitions or {}
    pinned_factors = known_factors or {}

    factors = [Decimal(0)] * len(rows)
    factors[anchor_index] = pinned_factors.get(target_date, anchor_factor)

    def step_ratio(prev_index, curr_index):
        prev_day = dates[prev_index]
        curr_day = dates[curr_index]
        prev_close = Decimal(str(rows[prev_index]["close"]))
        cash_div = dividends.get(curr_day, Decimal(0))
        split_mult = _transition_split_multiplier(splits, prev_day, curr_day)
        try:
            candidates = expected_transition_factors(prev_close, cash_div, split_mult)
        except ValueError:
            raise ValueError(f"{curr_day} 现金分红超过前收盘价，无法反推复权因子") from None
        observed = observed_map.get((prev_day, curr_day))
        if observed is not None and len(candidates) > 1:
            matching = min(candidates, key=lambda item: abs(observed / item - 1))
            if abs(observed / matching - 1) <= Decimal("0.0004"):
                return matching
        return candidates[0]

    # 向更早历史反推
    for index in range(anchor_index, 0, -1):
        prev_day = dates[index - 1]
        if prev_day in pinned_factors:
            factors[index - 1] = pinned_factors[prev_day]
        else:
            ratio = step_ratio(index - 1, index)
            factors[index - 1] = factors[index] / ratio

    # 若锚定日不是末日，向后顺推
    for index in range(anchor_index + 1, len(rows)):
        curr_day = dates[index]
        if curr_day in pinned_factors:
            factors[index] = pinned_factors[curr_day]
        else:
            ratio = step_ratio(index - 1, index)
            factors[index] = factors[index - 1] * ratio

    return [
        (Decimal(str(row["close"])) * factor).quantize(Decimal("0.00000001"))
        for row, factor in zip(rows, factors, strict=True)
    ]


def persist_verified_suspensions(db, code, suspension_audit, collected_at):
    """将至少双源核验一致的真实停牌日幂等持久化到数据库。

    功能：避免因子图等在线场景因历史上已确认停牌或份额折算停牌日被严格日历校验误拒。
    参数：
        db - SQLAlchemy 会话。
        code (str) - 六位 ETF 代码。
        suspension_audit (dict|None) - audited_suspensions 返回的停牌审计字典。
        collected_at (datetime) - 核验写入时间戳。
    返回：int - 写入或更新的停牌日期条数。
    """
    from app.models import InstrumentVerifiedSuspension

    if not isinstance(suspension_audit, dict):
        return 0
    available_count = suspension_audit.get("available_source_count")
    calendar_version = suspension_audit.get("calendar_version")
    records = suspension_audit.get("verified_suspensions") or []
    if (
        not isinstance(available_count, int)
        or available_count < 2
        or not calendar_version
        or not records
    ):
        return 0

    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        trade_date_text = record.get("trade_date")
        sources = sorted(
            {
                str(name)
                for name in (record.get("sources") or [])
                if isinstance(name, str) and name
            }
        )
        if not isinstance(trade_date_text, str) or len(sources) < 2:
            continue
        rows.append(
            {
                "instrument_code": code,
                "trade_date": date.fromisoformat(trade_date_text),
                "sources": sources,
                "calendar_version": str(calendar_version),
                "collected_at": collected_at,
            }
        )
    if not rows:
        return 0

    stmt = insert(InstrumentVerifiedSuspension.__table__).values(rows)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["instrument_code", "trade_date"],
            set_={
                "sources": stmt.excluded.sources,
                "calendar_version": stmt.excluded.calendar_version,
                "collected_at": stmt.excluded.collected_at,
            },
        )
    )
    return len(rows)


def free_backfill_end_date(current_dt):
    """确定上市至今日免费回补的安全截止日期，避免盘中写入未收盘K线。

    功能：北京时间 15:30 收盘后允许采集截至当日，盘中时段只采集截至昨日。
    参数：current_dt (datetime) - 带时区的当前北京时间。
    返回：date - 允许抓取的最大源交易日期。
    """
    if (current_dt.hour, current_dt.minute) >= (15, 30):
        return current_dt.date()
    return current_dt.date() - timedelta(days=1)


def backfill_instrument_history(
    db,
    code,
    *,
    end_date,
    collected_at,
    fetchers=None,
    apply=True,
    require_equity=False,
    min_date=MIN_CALENDAR_DATE,
    tencent_start_year=2004,
):
    """验证并按只增不改方式回补单只 ETF 自 MAX(2006-11-27, 上市日期) 以来的缺失行情。

    功能：读取本地已有行情作为重叠校准锚，执行分级免费源拉取、跨源比对与复权衔接反推，
          使用 on_conflict_do_nothing 只补齐缺失交易日，不覆盖既有记录。
    参数：
        db - SQLAlchemy 会话。
        code (str) - 六位 ETF 代码。
        end_date (date) - 最大允许源交易日。
        collected_at (datetime) - 本地采集时间戳。
        fetchers (dict|None) - 可选测试注入源。
        apply (bool) - 是否落库；False 时只返回校验结果。
        require_equity (bool) - 是否强制要求本地已有已核验权益资料。
        min_date (date|None) - 允许回补的最早日期（默认受交易所日历最早日期 2006-11-27 约束）。
        tencent_start_year (int) - 腾讯分段起始年份。
    返回：dict - 校验与回补明细（selected_source、listing_start、backfill_candidates 等）。
    """
    from app.models import BacktestSource, Candle

    existing_models = list(
        db.scalars(select(Candle).where(Candle.code == code).order_by(Candle.date))
    )
    existing = [
        {
            "trade_date": str(row.date),
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "adjusted_close": row.adjusted_close,
            "volume": row.volume,
            "amount": row.amount,
        }
        for row in existing_models
    ]
    source = db.get(BacktestSource, code)
    if require_equity and source is None:
        raise ValueError("缺少已核验权益资料，暂不反推历史复权收盘")

    verified = collect_and_verify_history(
        code,
        end_date=end_date,
        existing_rows=existing,
        fetchers=fetchers,
        tencent_start_year=tencent_start_year,
    )
    min_day_text = str(min_date) if min_date is not None else None
    rows = [
        row
        for row in verified["rows"]
        if min_day_text is None or row["trade_date"] >= min_day_text
    ]
    if not rows:
        raise ValueError(f"{code} 在 {min_day_text} 之后无有效行情")
    actions = source.corporate_actions if source else {"dividends": [], "splits": []}
    if existing and existing[0]["adjusted_close"] is not None:
        anchor_date = existing[0]["trade_date"]
        anchor_factor = Decimal(str(existing[0]["adjusted_close"])) / Decimal(
            str(existing[0]["close"])
        )
    else:
        anchor_date = rows[-1]["trade_date"]
        anchor_factor = Decimal(1)

    observed_transitions = {}
    for idx in range(1, len(existing)):
        prev_row = existing[idx - 1]
        curr_row = existing[idx]
        if (
            prev_row.get("adjusted_close") is not None
            and curr_row.get("adjusted_close") is not None
        ):
            prev_factor = Decimal(str(prev_row["adjusted_close"])) / Decimal(
                str(prev_row["close"])
            )
            curr_factor = Decimal(str(curr_row["adjusted_close"])) / Decimal(
                str(curr_row["close"])
            )
            observed_transitions[(prev_row["trade_date"], curr_row["trade_date"])] = (
                curr_factor / prev_factor
            )

    known_factors = {
        item["trade_date"]: Decimal(str(item["adjusted_close"]))
        / Decimal(str(item["close"]))
        for item in existing
        if item.get("adjusted_close") is not None
    }

    adjusted_series = compute_historical_adjusted_close(
        rows,
        actions,
        anchor_date=anchor_date,
        anchor_factor=anchor_factor,
        observed_transitions=observed_transitions,
        known_factors=known_factors,
    )
    existing_dates = {item["trade_date"] for item in existing}
    selected = verified["selected_source"]
    to_insert = []
    for row, adjusted_close in zip(rows, adjusted_series, strict=True):
        if row["trade_date"] in existing_dates:
            continue
        has_amount = row["amount"] is not None
        to_insert.append(
            {
                "instrument_code": code,
                "trade_date": date.fromisoformat(row["trade_date"]),
                "open_price": row["open"],
                "high_price": row["high"],
                "low_price": row["low"],
                "close_price": row["close"],
                "trading_volume": row["volume"],
                "trading_amount": row["amount"] if has_amount else Decimal(0),
                "price_change_pct": row["change_pct"],
                "adjusted_close_price": adjusted_close,
                "source_updated_at": (
                    f"free:{selected}"
                    if has_amount
                    else f"free:{selected}:no_amount"
                ),
                "collected_at": collected_at,
            }
        )

    if apply:
        if to_insert:
            for start_idx in range(0, len(to_insert), 500):
                batch = to_insert[start_idx : start_idx + 500]
                stmt = insert(Candle.__table__).values(batch)
                db.execute(
                    stmt.on_conflict_do_nothing(
                        index_elements=["instrument_code", "trade_date"]
                    )
                )
        written_suspensions = persist_verified_suspensions(
            db,
            code,
            (verified.get("cross_check") or {}).get("suspension_audit"),
            collected_at,
        )
        if to_insert or written_suspensions:
            db.commit()

    return {
        "status": "ok",
        "selected_source": selected,
        "listing_start": rows[0]["trade_date"],
        "end": rows[-1]["trade_date"],
        "total_rows": len(rows),
        "existing_rows": len(existing),
        "backfill_candidates": len(to_insert),
        "applied": bool(apply and to_insert),
        "source_status": verified["source_status"],
        "overlap_check": verified["overlap_check"],
        "cross_check": verified["cross_check"],
    }
