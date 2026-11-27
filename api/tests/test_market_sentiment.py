"""全市场恐贪源数据的边界与格式校验。"""

from datetime import date
from decimal import Decimal

import pytest

from app.market_sentiment import validate_response


def _body(*, score=0, factor_value=18.76, pct_year=50, pct_all=50):
    return {
        "date": "2026-11-27",
        "value": score,
        "desc": "恐惧",
        "history": [
            {"date": "2020-08-03", "value": 25},
            {"date": "2026-11-27", "value": score},
        ],
        "factors": [
            {
                "key": key,
                "name": name,
                "series": [
                    {
                        "date": "2026-11-27",
                        "value": factor_value if key == "volatility" else -1,
                        "pct_year": pct_year,
                        "pct_all": pct_all,
                    }
                ],
            }
            for key, name in (
                ("volatility", "指数波动：50ETF期权波动率"),
                ("bx", "避险天堂：股债回报差"),
                ("premium", "升贴水率：沪深300股指期货升贴水"),
                ("wz", "两市成交额"),
                ("strength", "股价强度：创新高个股数量占比"),
            )
        ],
    }


def test_zero_score_and_negative_regime_values_are_valid():
    total_rows, factor_rows = validate_response(_body(), date(2026, 11, 27))

    assert total_rows[-1] == {
        "trade_date": date(2026, 11, 27),
        "fear_greed_score": Decimal(0),
        "source_label": "恐惧",
    }
    assert {row["factor_key"] for row in factor_rows} == {
        "volatility",
        "bx",
        "premium",
        "wz",
        "strength",
    }
    assert {row["raw_value"] for row in factor_rows} == {
        Decimal("18.76"),
        Decimal(-1),
    }


@pytest.mark.parametrize("score", [-1, 101, None, "NaN", True])
def test_invalid_total_score_is_rejected(score):
    with pytest.raises(ValueError):
        validate_response(_body(score=score), date(2026, 11, 27))


@pytest.mark.parametrize("percentile", [-1, 101, "Infinity", True])
def test_invalid_source_percentile_is_rejected(percentile):
    with pytest.raises(ValueError):
        validate_response(
            _body(pct_year=percentile), date(2026, 11, 27)
        )


def test_rejects_incomplete_or_conflicting_factor_history():
    incomplete = _body()
    incomplete["factors"] = incomplete["factors"][:-1]
    with pytest.raises(ValueError, match="五项"):
        validate_response(incomplete, date(2026, 11, 27))

    conflicting = _body()
    conflicting["history"].append({"date": "2026-11-27", "value": 10})
    with pytest.raises(ValueError, match="冲突"):
        validate_response(conflicting, date(2026, 11, 27))


def test_rejects_future_observation():
    future = _body()
    future["factors"][0]["series"][0]["date"] = "2026-11-28"
    with pytest.raises(ValueError, match="晚于当前日期"):
        validate_response(future, date(2026, 11, 27))
