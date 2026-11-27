import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest


def row(day, price, volume=100):
    return {
        "trade_date": day,
        "open": str(price),
        "high": str(Decimal(str(price)) + Decimal(1)),
        "low": str(Decimal(str(price)) - Decimal(1)),
        "close": str(price),
        "volume": str(volume),
        "amount": str(Decimal(str(price)) * Decimal(str(volume))),
    }


def test_category_directory_keeps_single_etf_assets_as_their_own_categories():
    from app.factor_strategy_snapshot import category_for_code, independent_key

    assert category_for_code("510300") == "大盘宽基"
    assert category_for_code("518880") == "黄金"
    assert category_for_code("515880") == "通信设备"
    assert category_for_code("560780") == "半导体材料设备"
    assert category_for_code("999999") == "未分类"
    assert independent_key("510300", ["000300.SH"]) == "000300.SH"
    assert independent_key("518880", []) == "518880"


def test_factor_snapshot_item_freezes_category_independent_key_and_daily_truth():
    from app.factor_strategy_snapshot import build_factor_snapshot_item

    item, coverage = build_factor_snapshot_item(
        code="518880",
        name="测试黄金ETF",
        rows=[row("2026-01-05", 10), row("2026-01-06", 10.1)],
        actions={"dividends": [], "splits": []},
        indices=[],
        source={"market_source": "本地行情", "action_source_sha256": "a" * 64},
        turning={},
    )

    assert item["category"] == "黄金"
    assert item["independent_key"] == "518880"
    assert item["code"] == "518880"
    assert [value["trade_date"] for value in item["factor_truth"]] == [
        "2026-01-05",
        "2026-01-06",
    ]
    assert item["factor_truth"][0]["turning_bottom"] is False
    assert coverage["rows"] == 2


def test_factor_snapshot_allows_verified_suspensions_and_rejects_unverified_gaps():
    from app.factor_strategy_snapshot import build_factor_snapshot_item

    # 2026-01-05, 2026-01-07 为交易日，中间 2026-01-06 为模拟停牌日
    sparse_rows = [row("2026-01-05", 10), row("2026-01-07", 10.1)]
    with pytest.raises(ValueError, match="未核验交易日"):
        build_factor_snapshot_item(
            code="159915",
            name="创业板ETF",
            rows=sparse_rows,
            actions={"dividends": [], "splits": []},
            indices=["399006.SZ"],
            source={"market_source": "本地行情"},
            turning={},
        )

    item, coverage = build_factor_snapshot_item(
        code="159915",
        name="创业板ETF",
        rows=[row("2025-12-31", 9.9), *sparse_rows],
        actions={"dividends": [], "splits": []},
        indices=["399006.SZ"],
        source={"market_source": "本地行情"},
        turning={},
        start_date="2026-01-01",
        verified_suspensions=("2026-01-06",),
    )

    assert item["rows"][0]["trade_date"] == "2026-01-05"
    assert coverage["verified_suspensions"] == ["2026-01-06"]


def test_factor_snapshot_keeps_external_context_and_uses_prior_day_truth_only():
    from app.factor_strategy_snapshot import build_factor_snapshot_item

    rows = [row("2025-01-02", 10), row("2025-01-03", 10.1)]
    item, coverage = build_factor_snapshot_item(
        code="510300",
        name="沪深300ETF",
        rows=rows,
        actions={"dividends": [], "splits": []},
        indices=["000300.SH"],
        source={"market_source": "本地行情"},
        turning={},
        factor_context={
            "valuation_rows": [
                {
                    "trade_date": "2025-01-02",
                    "metric_key": "pb",
                    "metric_value": "1.2",
                    "value_status": "valid",
                }
            ],
            "sentiment_rows": None,
        },
    )

    assert item["factor_truth"][0]["valuation_low_percentile"] is False
    assert item["factor_truth"][1]["valuation_low_percentile"] is True
    assert item["factor_context"]["valuation_rows"][0]["trade_date"] == "2025-01-02"
    assert coverage["external"]["valuation"]["available"] is True


def test_factor_snapshot_passes_optional_benchmark_rows_to_factor_truth_without_requiring_them():
    from app.factor_strategy_snapshot import build_factor_snapshot_item

    rows = [row("2025-01-02", 10), row("2025-01-03", 10.1)]
    item, _ = build_factor_snapshot_item(
        code="510300",
        name="沪深300ETF",
        rows=rows,
        actions={"dividends": [], "splits": []},
        indices=["000300.SH"],
        source={"market_source": "本地行情"},
        turning={},
        factor_context={
            "benchmark_rows": [
                {"trade_date": "2025-01-02", "close": "4000"},
                {"trade_date": "2025-01-03", "close": "4010"},
            ]
        },
    )

    assert item["factor_context"]["benchmark_rows"][0]["trade_date"] == "2025-01-02"


def test_freeze_only_allows_explicit_three_source_suspension_audit():
    script = Path(__file__).resolve().parents[2] / "scripts" / "freeze_factor_strategy_research.py"
    spec = importlib.util.spec_from_file_location("freeze_factor_strategy_research", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {
        "items": {
            "159915": {
                "status": "ok",
                "cross_check": {
                    "suspension_audit": {
                        "available_source_count": 3,
                        "verified_suspensions": [
                            {
                                "trade_date": "2026-01-06",
                                "sources": ["eastmoney", "sina", "tencent"],
                            }
                        ],
                    }
                },
            }
        }
    }

    assert module._verified_suspensions_for(
        "159915", report, ["2026-01-05", "2026-01-07"]
    ) == ("2026-01-06",)

    report["items"]["159915"]["cross_check"]["suspension_audit"][
        "available_source_count"
    ] = 2
    with pytest.raises(ValueError, match="三方"):
        module._verified_suspensions_for(
            "159915", report, ["2026-01-05", "2026-01-07"]
        )


def test_freeze_parses_cli_window_dates_before_building_database_query():
    script = Path(__file__).resolve().parents[2] / "scripts" / "freeze_factor_strategy_research.py"
    spec = importlib.util.spec_from_file_location("freeze_factor_strategy_research", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.research_window_dates("2019-01-01", "2026-11-26") == (
        date(2019, 1, 1),
        date(2026, 11, 26),
    )
    with pytest.raises(ValueError, match="截止日期"):
        module.research_window_dates("2026-11-26", "2019-01-01")
