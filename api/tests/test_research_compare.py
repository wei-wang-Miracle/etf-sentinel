"""横向行情比较的共同区间与价格口径。"""

from datetime import date
from decimal import Decimal

from app.research_compare import compare_prices


def test_common_dates_are_required_and_prices_are_not_total_return():
    days = [date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 6)]
    series = {
        "510500": [
            (days[0], Decimal(10)),
            (days[1], Decimal(11)),
            (days[2], Decimal(12)),
        ],
        "512100": [(days[0], Decimal(10)), (days[2], Decimal(12))],
    }
    result = compare_prices(series, days)
    assert result["510500"]["change_pct"] == 20
    assert result["510500"]["points"] == [100, 110, 120]
    assert result["512100"]["status"] == "missing_dates"
    assert result["512100"]["change_pct"] is None


def test_zero_prices_are_not_used_for_comparison():
    day = date(2025, 1, 2)
    result = compare_prices({"x": [(day, Decimal(0))]}, [day])
    assert result["x"]["status"] == "invalid_price"


def test_common_endpoints_and_stale_observation():
    from datetime import date

    from app.research_compare import compare_observations

    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    result = compare_observations(
        {"a": [(days[0], 0), (days[-1], 10)], "b": [(days[1], 8)]}, days
    )
    assert result["a"]["latest"] == 10
    assert result["a"]["change"] == 10
    assert result["b"]["change"] is None
    assert result["b"]["status"] == "stale"
    assert result["a"]["points"][1][1] is None


def test_trend_drawdown_and_future_exclusion():
    from datetime import date

    from app.research_compare import trend_statistics

    days = [date(2026, 1, d) for d in (5, 6, 7)]
    result = trend_statistics(
        [(days[0], 10), (days[1], 12), (days[2], 9), (date(2026, 1, 8), 1000)], days
    )
    assert result["max_drawdown"] == -25
    assert abs(result["change_pct"] + 10) < 1e-8
    assert result["sample_count"] == 2
