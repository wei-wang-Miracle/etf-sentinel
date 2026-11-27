"""验证固定先验全期验收报告的无寻优口径。"""

import pytest


def test_parameter_perturbations_are_single_axis_and_do_not_select_winner():
    from app.shared_etf_fixed_prior import parameter_perturbations
    from app.shared_etf_research import FIXED_PRIOR_RULES

    points = parameter_perturbations(FIXED_PRIOR_RULES["range_breakout"])
    assert len(points) == 8
    assert {point["axis"] for point in points} == {
        "margin",
        "stop_atr",
        "trail_atr",
        "timeout",
    }
    assert {point["direction"] for point in points} == {"-20%", "+20%"}
    for point in points:
        changed = [
            key
            for key, value in FIXED_PRIOR_RULES["range_breakout"].items()
            if point["rule"][key] != value
        ]
        assert changed == [point["axis"]]


def test_regime_scorecard_measures_upside_and_loss_only_downside_capture():
    from app.shared_etf_fixed_prior import regime_scorecard

    benchmark = [
        ("2025-01-02", 1.0),
        ("2025-03-31", 1.1),
        ("2025-04-01", 1.1),
        ("2025-06-30", 0.99),
    ]
    strategy = [
        ("2025-01-02", 1.0),
        ("2025-03-31", 1.07),
        ("2025-04-01", 1.07),
        ("2025-06-30", 1.0593),
    ]
    scorecard = regime_scorecard(strategy, benchmark)
    assert scorecard["上涨"]["upside_capture"] == pytest.approx(0.7)
    assert scorecard["下跌"]["downside_capture"] == pytest.approx(0.1)
    assert scorecard["下跌"]["max_drawdown"] == pytest.approx(-0.01)


def test_combination_keeps_equal_weight_daily_net_value():
    from app.shared_etf_fixed_prior import combine_nav_curves

    combined = combine_nav_curves(
        [
            [("2025-01-02", 1.0), ("2025-01-03", 1.1)],
            [("2025-01-02", 1.0), ("2025-01-03", 0.98)],
        ]
    )
    assert combined == [("2025-01-02", 1.0), ("2025-01-03", 1.04)]


def test_transfer_coverage_reports_absent_assets_instead_of_fabricating_results():
    from app.shared_etf_fixed_prior import transfer_coverage

    result = transfer_coverage({"518880": {"rows": [{}] * 66}})
    assert result["518880"] == {"status": "可评估"}
    assert result["515880"] == {"status": "未验证", "reason": "冻结输入未包含标的"}
    assert result["560780"] == {"status": "未验证", "reason": "冻结输入未包含标的"}


def test_fixed_account_uses_65_bars_before_first_execution():
    from datetime import date, timedelta

    from app.shared_etf_fixed_prior import evaluate
    from app.shared_etf_research import FIXED_PRIOR_RULES, prepare_market

    rows = []
    for index, close in enumerate([10 + i * 0.015 for i in range(64)] + [11.2, 11.1, 11.0]):
        rows.append(
            {
                "trade_date": str(date(2025, 1, 1) + timedelta(days=index)),
                "open": str(close),
                "high": str(close + 0.1),
                "low": str(close - 0.2),
                "close": str(close),
                "volume": "1500" if index == 64 else "1000",
            }
        )
    item = {
        "rows": rows,
        "dividends": [],
        "dates": [row["trade_date"] for row in rows],
        "market": prepare_market(rows, [], {}),
    }
    account = evaluate(
        item,
        rows[65]["trade_date"],
        rows[-1]["trade_date"],
        FIXED_PRIOR_RULES["range_breakout"],
    )
    assert account["daily"][0]["trade_date"] == rows[65]["trade_date"]
    assert account["fills"][0]["signal_date"] == rows[64]["trade_date"]
