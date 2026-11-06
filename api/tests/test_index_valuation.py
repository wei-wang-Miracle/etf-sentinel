"""指数估值口径及不含未来信息的分位测试。"""

from datetime import date
from decimal import Decimal

import pytest

from app.index_valuation import INDEX_CATALOG, parse_history, rolling_percentiles


def test_catalog_covers_current_twenty_etfs():
    assert len(INDEX_CATALOG) == 8
    codes = [code for _, _, funds in INDEX_CATALOG.values() for code in funds]
    assert len(codes) == len(set(codes)) == 20
    assert "000680.SH" not in INDEX_CATALOG
    assert "510500" in INDEX_CATALOG["000905.SH"][2]
    assert "512100" in INDEX_CATALOG["000852.SH"][2]


def history(metric, values):
    return {
        "code": "000905.SH",
        "metric": metric,
        "series": [
            {"date": f"2026-01-{i + 1:02d}", "value": value}
            for i, value in enumerate(values)
        ],
    }


def test_metric_zero_and_negative_semantics():
    assert parse_history(history("pe", [0, -1, 10]), "000905.SH", "pe") == [
        (date(2026, 1, 1), Decimal(0), "not_applicable"),
        (date(2026, 1, 2), Decimal(-1), "not_applicable"),
        (date(2026, 1, 3), Decimal(10), "valid"),
    ]
    for metric in ("xilv", "roe", "premium_diff"):
        assert parse_history(history(metric, [0]), "000905.SH", metric)[0][2] == "valid"
    assert (
        parse_history(history("premium_diff", [-2]), "000905.SH", "premium_diff")[0][2]
        == "valid"
    )
    assert parse_history(history("roe", [9.89]), "000905.SH", "roe")[0][1] == Decimal(
        "9.89"
    )


@pytest.mark.parametrize("value", [True, "NaN", "Infinity"])
def test_invalid_numeric_rejected(value):
    with pytest.raises(ValueError):
        parse_history(history("pb", [value]), "000905.SH", "pb")


def test_missing_value_preserved_and_duplicate_dates_rejected():
    assert parse_history(history("pb", [None]), "000905.SH", "pb")[0][2] == "missing"
    body = history("pb", [1])
    body["series"] *= 2
    with pytest.raises(ValueError):
        parse_history(body, "000905.SH", "pb")


def test_wrong_code_metric_future_empty_rejected():
    for body in ({}, history("pb", []), history("pe", [1])):
        with pytest.raises(ValueError):
            parse_history(body, "000905.SH", "pb")
    body = history("pb", [1])
    body["series"][0]["date"] = "2099-01-01"
    with pytest.raises(ValueError):
        parse_history(body, "000905.SH", "pb")


def test_percentiles_ties_missing_and_no_future():
    rows = [
        (
            date(2020, 1, i + 1),
            Decimal(v) if v is not None else None,
            "valid" if v is not None else "missing",
        )
        for i, v in enumerate([2, 1, 2, None, 9])
    ]
    result = rolling_percentiles(rows)
    assert result[:4] == [0, 0, pytest.approx(100 / 3), None]
    assert result[:4] == rolling_percentiles(rows[:4])


def test_percentile_calendar_year_boundary_and_invalid_values():
    rows = [
        (date(2016, 2, 28), Decimal(1), "valid"),
        (date(2016, 2, 29), Decimal(2), "valid"),
        (date(2026, 2, 28), Decimal(3), "valid"),
        (date(2026, 3, 1), Decimal(4), "valid"),
        (date(2026, 3, 2), Decimal(0), "not_applicable"),
    ]
    assert rolling_percentiles(rows) == [0, 50, pytest.approx(200 / 3), 50, None]
