"""FundDB ETF 截面与详情响应解析边界。"""

from datetime import date
from decimal import Decimal

import pytest

from app.etf_catalog import parse_catalog_page, parse_fund_detail


def _item(**changes):
    item = {
        "fund_int_code": "510500",
        "fund_name": "中证500ETF",
        "_fullname": "测试基金全称",
        "category_0": "股票型ETF",
        "category_1": "中证500",
        "gaikuang_genzongcode": "000905.SH",
        "gaikuang_genzongzhishu": "中证500",
        "setup_date": "2013-02-06",
        "lianjie_code": "160119",
        "guimo_date": "2026-11-27",
        "guimo_zuixin_guimo": "12.5",
        "guimo_zuixin_fene": "3.4",
        "guimo_fene_7": "0.2",
        "guimo_fene_30": "-0.3",
        "diff_deal_price": "0.12",
        "feilv_guanlifei": "0.5",
        "feilv_tuoguanfei": "0.1",
        "sg_status": "开放申购",
        "sh_status": "开放赎回",
    }
    item.update(changes)
    return item


def test_parses_real_wrapped_catalog_and_flow_fields():
    rows, total = parse_catalog_page(
        {"code": 0, "data": {"lists": [_item()], "total": 1}},
        date(2026, 11, 28),
    )

    assert total == 1
    assert rows[0]["instrument_code"] == "510500"
    assert rows[0]["tracking_index_code"] == "000905.SH"
    assert rows[0]["setup_date"] == date(2013, 2, 6)
    assert rows[0]["flow"] == {
        "trade_date": date(2026, 11, 27),
        "unit_shares_100m": Decimal("3.4"),
        "aum_100m": Decimal("12.5"),
        "net_share_flow_7d_100m": Decimal("0.2"),
        "net_share_flow_30d_100m": Decimal("-0.3"),
        "discount_premium_pct": Decimal("0.12"),
        "purchase_status": "开放申购",
        "redeem_status": "开放赎回",
    }


def test_accepts_flat_catalog_list_but_rejects_invalid_identity_and_future_flow_date():
    rows, total = parse_catalog_page([_item()], date(2026, 11, 28))
    assert total == 1 and rows[0]["instrument_code"] == "510500"

    with pytest.raises(ValueError, match="证券代码"):
        parse_catalog_page([_item(fund_int_code="bad")], date(2026, 11, 28))
    with pytest.raises(ValueError, match="晚于当前日期"):
        parse_catalog_page([_item(guimo_date="2026-11-29")], date(2026, 11, 28))


def test_normalizes_source_placeholder_number_to_missing_value():
    rows, _ = parse_catalog_page([_item(diff_deal_price="--")], date(2026, 11, 28))
    assert rows[0]["flow"]["discount_premium_pct"] is None


def test_extracts_detail_index_correlation_from_real_nested_shape():
    detail = parse_fund_detail(
        {
            "code": 0,
            "data": {
                "index_corr": [
                    {"code": "000300.SH", "corr": 0.91, "market": "a", "name": "沪深300"},
                    {"code": "000905.SH", "corr": 0.9783, "market": "a", "name": "中证500"},
                ]
            },
        },
        "000905.SH",
    )

    assert detail == {"tracking_index_code": "000905.SH", "index_corr": Decimal("0.9783")}


@pytest.mark.parametrize("corr", [-0.1, 1.1, "NaN", True])
def test_rejects_invalid_detail_correlation(corr):
    with pytest.raises(ValueError):
        parse_fund_detail(
            {"data": {"index_corr": [{"code": "000905.SH", "corr": corr}]}},
            "000905.SH",
        )
