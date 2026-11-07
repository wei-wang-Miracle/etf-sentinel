"""单标的资金加权收益与资金流核算。"""

from datetime import date
from decimal import Decimal

import pytest

from app.review_math import net_pnl, xirr


def test_net_pnl_counts_fees_only_once():
    assert net_pnl(0, 6600, [Decimal(-10001), Decimal("4799.52")]) == Decimal("1398.52")


def test_xirr_includes_initial_value_and_uses_calendar_dates():
    result = xirr(
        [(date(2025, 1, 1), Decimal(-10000)), (date(2026, 1, 1), Decimal(11000))]
    )
    assert result == pytest.approx(0.1, abs=1e-8)


def test_xirr_does_not_guess_multiple_roots():
    flows = [
        (date(2023, 1, 1), Decimal(-100)),
        (date(2024, 1, 1), Decimal(230)),
        (date(2025, 1, 1), Decimal(-132)),
    ]
    assert xirr(flows) is None
