"""外部估值和情绪因子必须按严格历史可得日期对齐。"""

from datetime import date, timedelta


def _rows(length):
    return [
        {"trade_date": str(date(2025, 1, 1) + timedelta(days=index))}
        for index in range(length)
    ]


def test_external_factor_truth_uses_only_observations_strictly_before_etf_day():
    from app.research_factor_context import build_external_factor_truth

    rows = _rows(7)
    valuation_rows = [
        {
            "trade_date": f"2025-01-0{index}",
            "metric_key": "pb",
            "metric_value": str(index),
            "value_status": "valid",
        }
        for index in range(1, 6)
    ]
    sentiment_rows = [
        {"trade_date": "2025-01-01", "fear_greed_score": "10"},
        {"trade_date": "2025-01-02", "fear_greed_score": "10"},
        {"trade_date": "2025-01-03", "fear_greed_score": "25"},
        {"trade_date": "2025-01-04", "fear_greed_score": "85"},
    ]

    truth, coverage = build_external_factor_truth(
        rows,
        valuation_rows=valuation_rows,
        sentiment_rows=sentiment_rows,
    )

    assert truth[0]["valuation_low_percentile"] is False
    assert truth[1]["valuation_low_percentile"] is True
    assert truth[4]["valuation_high_percentile"] is False
    assert truth[5]["valuation_high_percentile"] is True
    assert truth[1]["sentiment_extreme_fear"] is True
    assert truth[2]["sentiment_fear_rebound"] is False
    assert truth[3]["sentiment_fear_rebound"] is True
    assert truth[4]["sentiment_extreme_greed"] is True
    assert coverage["valuation"]["available"] is True
    assert coverage["sentiment"]["available"] is True


def test_external_factor_truth_ignores_invalid_valuation_and_marks_unmapped_sentiment_unavailable():
    from app.research_factor_context import build_external_factor_truth

    rows = _rows(3)
    truth, coverage = build_external_factor_truth(
        rows,
        valuation_rows=[
            {
                "trade_date": "2025-01-01",
                "metric_key": "pe",
                "metric_value": "-1",
                "value_status": "not_applicable",
            }
        ],
    )

    assert not any(item["valuation_low_percentile"] for item in truth)
    assert not any(item["valuation_high_percentile"] for item in truth)
    assert not any(item["sentiment_extreme_fear"] for item in truth)
    assert coverage["valuation"]["available"] is False
    assert coverage["sentiment"] == {"available": False, "reason": "未建立ETF–恐贪类别映射"}


def test_external_valuation_uses_all_valid_metrics_strictly_before_the_etf_day():
    from app.research_factor_context import build_external_factor_truth

    rows = _rows(7)
    valuation_rows = [
        {
            "trade_date": f"2025-01-0{index}",
            "metric_key": metric,
            "metric_value": str(value),
            "value_status": "valid",
        }
        for metric in ("premium_diff", "xilv", "roe")
        for index, value in enumerate((0, 1, 2, 3), start=1)
    ]
    valuation_rows.extend(
        [
            {
                "trade_date": "2025-01-10",
                "metric_key": "xilv",
                "metric_value": "999",
                "value_status": "not_applicable",
            },
            {
                "trade_date": "2025-01-10",
                "metric_key": "premium_diff",
                "metric_value": "-5",
                "value_status": "valid",
            },
        ]
    )

    truth, coverage = build_external_factor_truth(rows, valuation_rows=valuation_rows)

    assert truth[1]["erp_low_percentile"] is True
    assert truth[3]["erp_high_percentile"] is False
    assert truth[4]["erp_high_percentile"] is True
    assert truth[4]["dividend_yield_high"] is True
    assert coverage["valuation"]["metrics"]["premium_diff"]["available"] is True
    assert coverage["valuation"]["metrics"]["xilv"]["first_source_date"] == "2025-01-01"


def test_market_regime_factors_use_only_strictly_prior_market_observations():
    from app.research_factor_context import build_external_factor_truth

    rows = _rows(4)
    truth, coverage = build_external_factor_truth(
        rows,
        market_rows=[
            {"trade_date": "2025-01-01", "fear_greed_score": "20"},
            {"trade_date": "2025-01-03", "fear_greed_score": "80"},
        ],
        market_regime_rows=[
            {"factor_key": "volatility", "trade_date": "2025-01-01", "raw_value": "23"},
            {"factor_key": "premium", "trade_date": "2025-01-01", "raw_value": "-11"},
            {"factor_key": "strength", "trade_date": "2025-01-01", "raw_value": "0.8"},
        ],
    )

    assert truth[0]["market_fear_extreme"] is False
    assert truth[1]["market_fear_extreme"] is True
    assert truth[1]["market_ivix_high"] is True
    assert truth[1]["market_breadth_weak"] is True
    assert truth[1]["market_futures_deep_discount"] is True
    assert truth[3]["market_greed_extreme"] is True
    assert coverage["market_regime"]["available"] is True
    assert coverage["market_regime"]["first_source_date"] == "2025-01-01"
