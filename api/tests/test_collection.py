"""采集边界与数据质量的回归验证。"""

from datetime import date

import pytest

from app.collection import month_ranges, validate_row


def test_month_ranges():
    assert list(month_ranges(date(2026, 1, 30), date(2026, 2, 2))) == [
        (date(2026, 1, 30), date(2026, 1, 31)),
        (date(2026, 2, 1), date(2026, 2, 2)),
    ]


def row():
    return {
        "STOCK_CODE": "510500",
        "TRADE_DATE": "2026-06-01",
        "OPEN_PRICE": 1,
        "HIGH_PRICE": 2,
        "LOW_PRICE": 0.5,
        "CLOSE_PRICE": 1.5,
        "VOLUME": 100,
        "AMOUNT": 150,
    }


def test_reject_unrequested_symbol():
    with pytest.raises(ValueError):
        validate_row(row(), "512100", date(2026, 6, 1), date(2026, 6, 30))


def test_reject_invalid_price():
    data = row()
    data["HIGH_PRICE"] = 0.8
    with pytest.raises(ValueError):
        validate_row(data, "510500", date(2026, 6, 1), date(2026, 6, 30))


def test_valid_row():
    assert (
        validate_row(row(), "510500", date(2026, 6, 1), date(2026, 6, 30))["close"]
        == 1.5
    )


def test_reject_outside_dates():
    with pytest.raises(ValueError):
        validate_row(row(), "510500", date(2026, 6, 2), date(2026, 6, 30))


def test_reject_nan_volume():
    data = row()
    data["VOLUME"] = "NaN"
    with pytest.raises(ValueError):
        validate_row(data, "510500", date(2026, 6, 1), date(2026, 6, 30))
