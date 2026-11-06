"""国家队比例采集的源契约与固定基准校验。"""

from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest

from app.national_team import ESTIMATION_START, validate_etf, validate_response


def etf(code="510300", ratio=66.98):
    """最小源数据，不依赖价格字段。"""
    return {
        "code": code,
        "name": "测试ETF",
        "index": "沪深300",
        "hold_pct": 82.76,
        "points": [{"date": "2026-11-05T00:00:00+08:00", "fe": 100, "nat_pct": ratio}],
    }


def body(items=None):
    """固定基准响应样例。"""
    return {
        "code": 0,
        "data": {
            "start": str(ESTIMATION_START),
            "end": "2026-11-06",
            "etfs": items if items is not None else [etf()],
        },
    }


def test_only_ratio_metadata_and_actual_source_date_are_retained():
    """缺少源价格仍可入库，日期取源交易日而非请求截止日。"""
    meta, rows = validate_etf(etf(), date(2026, 11, 6))
    assert meta["instrument_code"] == "510300"
    assert rows == [
        {
            "instrument_code": "510300",
            "trade_date": date(2026, 11, 5),
            "estimated_holding_pct": Decimal("66.98000000"),
        }
    ]


def test_zero_ratio_is_valid_but_missing_share_history_is_null():
    """份额有效时零比例有效，源零份额不能误报零持仓。"""
    item = etf(ratio=0)
    assert validate_etf(item, date(2026, 11, 6))[1][0]["estimated_holding_pct"] == 0
    item["points"][0]["fe"] = 0
    assert validate_etf(item, date(2026, 11, 6))[1][0]["estimated_holding_pct"] is None


@pytest.mark.parametrize("ratio", [-1, 101, True, "NaN", "Infinity"])
def test_invalid_ratio_rejects_entire_etf(ratio):
    """非法比例不能部分落库。"""
    with pytest.raises(ValueError):
        validate_etf(etf(ratio=ratio), date(2026, 11, 6))


def test_conflicting_duplicate_dates_rejected():
    """同日冲突不能按源顺序任意覆盖。"""
    item = etf()
    other = deepcopy(item["points"][0])
    other["nat_pct"] = 50
    item["points"].append(other)
    with pytest.raises(ValueError):
        validate_etf(item, date(2026, 11, 6))


@pytest.mark.parametrize("day", ["invalid", "2025-12-31", "2026-11-07"])
def test_date_must_be_within_fixed_requested_range(day):
    """不接受起点之前、未来或非法日期。"""
    item = etf()
    item["points"][0]["date"] = day
    with pytest.raises(ValueError):
        validate_etf(item, date(2026, 11, 6))


def test_empty_history_and_duplicate_codes_rejected():
    """空历史或重复基金不能默认为成功。"""
    item = etf()
    item["points"] = []
    with pytest.raises(ValueError):
        validate_etf(item, date(2026, 11, 6))
    with pytest.raises(ValueError):
        validate_response(body([etf(), etf()]), date(2026, 11, 6))


@pytest.mark.parametrize("change", ["status", "start", "end", "empty"])
def test_response_status_and_estimation_basis_are_verified(change):
    """拒绝错误响应及被源修改的估算起点，避免拼接不同口径。"""
    value = body()
    if change == "status":
        value["code"] = 1
    elif change == "empty":
        value["data"]["etfs"] = []
    else:
        value["data"][change] = "2026-11-01"
    with pytest.raises(ValueError):
        validate_response(value, date(2026, 11, 6))
