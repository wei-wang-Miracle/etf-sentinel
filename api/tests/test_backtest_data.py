"""验证权益解析、交易日完整性与未登记分红跳变保护。"""

from copy import deepcopy

import pytest

from app.backtest_data import (
    parse_actions,
    post_split_rows,
    validate_market,
)


def test_explicit_empty_action_tables_are_valid():
    html = """
    <table><tr><th>权益登记日</th></tr><tr><td>暂无分红信息!</td></tr></table>
    <table><tr><th>拆分折算日</th></tr><tr><td>暂无拆分信息!</td></tr></table>
    """
    assert parse_actions(html) == {"dividends": [], "splits": []}


def test_empty_action_tables_without_source_statement_are_rejected():
    html = "<table><tr><th>权益登记日</th></tr></table>" \
        "<table><tr><th>拆分折算日</th></tr></table>"
    with pytest.raises(ValueError):
        parse_actions(html)

HTML = """<table><tr><th>年份</th><th>权益登记日</th><th>除息日</th><th>每10份分红</th><th>分红发放日</th></tr>
<tr><td>2026年</td><td>2026-01-15</td><td>2026-01-16</td><td>每10份派现金0.6200元</td><td>2026-01-21</td></tr></table>
<table><tr><th>年份</th><th>拆分折算日</th><th>拆分类型</th><th>拆分折算比例</th></tr>
<tr><td>2022年</td><td>2022-08-26</td><td>份额分拆</td><td>1:1.1454</td></tr></table>"""


def test_cash_dividend_is_per_share_and_split_history_is_retained():
    actions = parse_actions(HTML)
    assert actions["dividends"][0]["cash_per_share"] == "0.0620"
    assert actions["splits"][0]["effective_date"] == "2022-08-26"
    with pytest.raises(ValueError, match="权益"):
        parse_actions("<html>访问失败</html>")


def test_same_day_record_and_ex_dividend_date_are_supported():
    html = HTML.replace("2026-01-15</td><td>2026-01-16", "2026-01-15</td><td>2026-01-15")
    actions = parse_actions(html)
    assert actions["dividends"][0]["record_date"] == "2026-01-15"
    assert actions["dividends"][0]["ex_date"] == "2026-01-15"


def market():
    return [
        {
            "trade_date": day,
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10",
            "volume": "100",
            "adjusted_close": "10",
        }
        for day in ("2026-01-14", "2026-01-15", "2026-01-16")
    ]


def test_missing_trading_day_and_unknown_adjustment_jump_are_blocked():
    with pytest.raises(ValueError, match="缺少交易日"):
        validate_market(market()[::2], {"dividends": [], "splits": []})
    rows = market()
    rows[-1]["adjusted_close"] = "11"
    with pytest.raises(ValueError, match="复权因子"):
        validate_market(rows, {"dividends": [], "splits": []})


def test_known_dividend_and_rounding_tolerance_pass_but_splits_block():
    rows = market()
    actions = parse_actions(HTML)
    rows[-1]["adjusted_close"] = "10.0624"
    validate_market(rows, actions)
    bad = deepcopy(actions)
    bad["splits"] = [{"effective_date": "2026-01-15", "ratio": "1:2"}]
    with pytest.raises(ValueError, match="折算"):
        validate_market(rows, bad)


def test_split_before_requested_interval_is_removed_before_validation():
    rows = [
        {"trade_date": day, "close": "1", "adjusted_close": "1"}
        for day in ("2024-09-19", "2024-09-20", "2024-09-23")
    ]
    actions = [{"effective_date": "2024-09-20", "ratio": "1:0.4998"}]

    filtered = post_split_rows(rows, actions, "2024-11-13")

    assert [row["trade_date"] for row in filtered] == ["2024-09-23"]


def test_zero_volume_and_invalid_prices_are_refused_as_unsupported_input():
    """缺少事前可知停牌状态，不以全天零成交量挑选开盘成交。"""
    rows = market()
    rows[1]["volume"] = "0"
    with pytest.raises(ValueError, match="零成交量"):
        validate_market(rows, {"dividends": [], "splits": []})
    rows = market()
    rows[1]["adjusted_close"] = None
    with pytest.raises(ValueError, match="缺失"):
        validate_market(rows, {"dividends": [], "splits": []})
