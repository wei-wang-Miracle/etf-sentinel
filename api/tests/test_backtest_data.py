"""验证权益解析、交易日完整性与未登记分红跳变保护。"""

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from app import backtest_data
from app.backtest_data import (
    fetch_actions,
    front_adjusted_ohlc_rows,
    indicator_ohlc_rows,
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


def test_fetch_actions_retries_temporary_source_failure(monkeypatch):
    """临时服务异常不能让日常批量权益核验留下单只空洞。"""
    calls = []

    def source_get(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            return httpx.Response(503, request=httpx.Request("GET", args[0]))
        return httpx.Response(
            200, content=HTML.encode(), request=httpx.Request("GET", args[0])
        )

    monkeypatch.setattr(backtest_data.httpx, "get", source_get)
    monkeypatch.setattr(
        backtest_data, "time", SimpleNamespace(sleep=lambda _: None), raising=False
    )

    actions = fetch_actions("510500")

    assert len(calls) == 3
    assert actions["actions"]["dividends"][0]["cash_per_share"] == "0.0620"


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


def test_known_split_produces_continuous_display_and_causal_indicator_prices():
    rows = [
        {
            "trade_date": "2026-01-14",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10",
            "volume": "100",
            "adjusted_close": "10",
        },
        {
            "trade_date": "2026-01-15",
            "open": "5",
            "high": "5.5",
            "low": "4.5",
            "close": "5",
            "volume": "200",
            "adjusted_close": "10",
        },
    ]
    actions = {
        "dividends": [],
        "splits": [{"effective_date": "2026-01-14", "ratio": "1:2"}],
    }

    validate_market(rows, actions, allow_splits=True)

    display = front_adjusted_ohlc_rows(rows)
    indicators = indicator_ohlc_rows(rows, actions)
    assert [row["close"] for row in display] == ["5", "5"]
    assert [row["high"] for row in display] == ["5.5", "5.5"]
    assert [row["close"] for row in indicators] == ["10", "10"]
    assert [row["volume"] for row in indicators] == ["100", "100"]


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


def test_validate_market_allows_verified_suspensions_and_pre_calendar_boundary():
    """跨源核验的真实停牌日可放行，未核验缺日仍拒绝并指出首日。"""
    rows = market()
    with pytest.raises(ValueError, match="缺少交易日（首日 2026-01-15，共 1 日未核验停牌）".replace("(", "\\(").replace(")", "\\)")):
        validate_market(rows[::2], {"dividends": [], "splits": []})

    validate_market(
        rows[::2],
        {"dividends": [], "splits": []},
        verified_suspensions=("2026-01-15",),
    )

    boundary_rows = [
        {
            "trade_date": day,
            "open": "1",
            "high": "1.1",
            "low": "0.9",
            "close": "1",
            "volume": "100",
            "adjusted_close": "1",
        }
        for day in ("2006-11-27", "2006-11-28", "2006-11-29")
    ]
    with pytest.raises(ValueError, match="超出当前日历覆盖"):
        validate_market(boundary_rows, {"dividends": [], "splits": []})
    validate_market(
        boundary_rows,
        {"dividends": [], "splits": []},
        ignore_pre_calendar_boundary=True,
    )


def test_validate_market_accepts_same_day_split_with_post_split_dividend_and_blocks_bad_factor():
    """同日发生折算与分红时，兼容按拆后份额派息，但仍严格拦截不匹配的复权跃迁。"""
    rows = [
        {
            "trade_date": "2024-11-29",
            "open": "6.071",
            "high": "6.160",
            "low": "6.070",
            "close": "6.159",
            "volume": "100",
            "adjusted_close": "6.8820",
        },
        {
            "trade_date": "2024-12-02",
            "open": "2.461",
            "high": "2.470",
            "low": "2.360",
            "close": "2.374",
            "volume": "250",
            "adjusted_close": "6.9987",
        },
    ]
    actions = {
        "dividends": [
            {
                "record_date": "2024-11-29",
                "ex_date": "2024-12-02",
                "pay_date": "2024-12-03",
                "cash_per_share": "0.1292",
            }
        ],
        "splits": [{"effective_date": "2024-11-29", "ratio": "1:2.5000"}],
    }
    validate_market(rows, actions, allow_splits=True)

    bad_rows = deepcopy(rows)
    bad_rows[1]["adjusted_close"] = "7.5000"
    with pytest.raises(ValueError, match="复权因子与已核实分红不符"):
        validate_market(bad_rows, actions, allow_splits=True)
