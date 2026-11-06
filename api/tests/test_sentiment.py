"""行业恐贪增量边界与源数据质量验证。"""

from datetime import date
from decimal import Decimal

import pytest

from app.sentiment import request_years, validate_series


def test_first_collection_is_five_years():
    assert request_years(None, date(2026, 11, 6)) == 5


def test_incremental_minimum_window():
    assert request_years(date(2026, 11, 5), date(2026, 11, 6)) == 1
    assert request_years(date(2024, 1, 1), date(2026, 11, 6)) == 3


def test_zero_is_valid():
    rows = validate_series(
        {"key": "zj", "series": [{"date": "2026-11-05", "value": 0, "close": 1200}]},
        "zj",
    )
    assert rows[0]["fear_greed_score"] == Decimal(0)


@pytest.mark.parametrize("score", [-1, 101, None, "NaN", True])
def test_invalid_scores_are_rejected(score):
    with pytest.raises(ValueError):
        validate_series(
            {
                "key": "gf",
                "series": [{"date": "2026-11-05", "value": score, "close": 100}],
            },
            "gf",
        )


def test_conflicting_duplicate_date_is_rejected():
    with pytest.raises(ValueError):
        validate_series(
            {
                "key": "gf",
                "series": [
                    {"date": "2026-11-05", "value": 10, "close": 100},
                    {"date": "2026-11-05", "value": 20, "close": 100},
                ],
            },
            "gf",
        )


def test_wrong_category_is_rejected():
    with pytest.raises(ValueError):
        validate_series({"key": "qs", "series": []}, "gf")
