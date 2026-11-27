"""验证共享 ETF 外部冻结输入的研究专用转换。"""

from decimal import Decimal

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


def test_normalize_split_history_converts_prior_prices_volumes_and_dividends():
    from app.shared_etf_snapshot import normalize_split_history

    rows = [
        row("2026-01-02", 10, 100),
        row("2026-01-05", 5, 200),
    ]
    actions = {
        "dividends": [
            {
                "record_date": "2026-01-02",
                "ex_date": "2026-01-02",
                "pay_date": "2026-01-03",
                "cash_per_share": "0.2",
            }
        ],
        "splits": [{"effective_date": "2026-01-02", "ratio": "1:2"}],
    }

    normalized_rows, normalized_actions, conversion = normalize_split_history(
        rows, actions
    )

    assert normalized_rows[0]["open"] == "5"
    assert normalized_rows[0]["high"] == "5.5"
    assert normalized_rows[0]["low"] == "4.5"
    assert normalized_rows[0]["close"] == "5"
    assert normalized_rows[0]["volume"] == "200"
    assert normalized_rows[0]["amount"] == "1000"
    assert normalized_rows[1] == rows[1]
    assert normalized_actions == {
        "dividends": [
            {
                **actions["dividends"][0],
                "cash_per_share": "0.1",
            }
        ],
        "splits": [],
    }
    assert conversion == [
        {
            "effective_date": "2026-01-02",
            "ratio": "1:2",
            "share_multiplier": "2",
        }
    ]


def test_validate_snapshot_rows_rejects_a_missing_exchange_session():
    from app.shared_etf_snapshot import validate_snapshot_rows

    rows = [row("2026-01-05", 10), row("2026-01-07", 10)]
    with pytest.raises(ValueError, match="行情缺少交易日"):
        validate_snapshot_rows(rows, {"dividends": [], "splits": []})


def test_validate_snapshot_rows_rejects_unconverted_split_events():
    from app.shared_etf_snapshot import validate_snapshot_rows

    rows = [row("2026-01-05", 10), row("2026-01-06", 10)]
    with pytest.raises(ValueError, match="未标准化的份额折算"):
        validate_snapshot_rows(
            rows,
            {"dividends": [], "splits": [{"effective_date": "2026-01-05", "ratio": "1:2"}]},
        )


def test_build_snapshot_item_keeps_transfer_outside_the_wide_index_pool():
    from app.shared_etf_snapshot import build_snapshot_item

    rows = [row("2026-01-05", 10, 100), row("2026-01-06", 5, 200)]
    actions = {
        "dividends": [],
        "splits": [{"effective_date": "2026-01-05", "ratio": "1:2"}],
    }

    item, coverage = build_snapshot_item(
        code="515880",
        name="测试行业ETF",
        rows=rows,
        actions=actions,
        indices=[],
        role="transfer",
        source={"market_source": "本地行情", "action_source_sha256": "a" * 64},
    )

    assert item["role"] == "transfer"
    assert item["indices"] == []
    assert item["actions"]["splits"] == []
    assert item["excluded_splits"] == []
    assert item["rows"][0]["close"] == "5"
    assert coverage == {
        "rows": 2,
        "start": "2026-01-05",
        "end": "2026-01-06",
        "normalized_splits": [
            {
                "effective_date": "2026-01-05",
                "ratio": "1:2",
                "share_multiplier": "2",
            }
        ],
    }


def test_snapshot_roles_freeze_the_eight_wide_candidates_and_three_transfers():
    from app.shared_etf_snapshot import CORE_CODES, SNAPSHOT_CODES, role_for_code

    assert CORE_CODES == (
        "510180",
        "510050",
        "510300",
        "588080",
        "512100",
        "510500",
        "159915",
        "159531",
    )
    assert SNAPSHOT_CODES[-3:] == ("518880", "515880", "560780")
    assert role_for_code("510300") == "core"
    assert role_for_code("515880") == "transfer"
    with pytest.raises(ValueError, match="不在固定先验外部验证范围"):
        role_for_code("159205")


def test_representative_selection_ignores_transfer_roles_even_with_an_index_link():
    from app.shared_etf_fixed_prior import FIRST_EXECUTION, representative_codes

    rows = [row(f"2026-01-{index + 1:02d}", 10, 100) for index in range(66)]
    transfer_rows = [
        row(f"2026-01-{index + 1:02d}", 10, 200) for index in range(66)
    ]
    data = {
        "510300": {
            "role": "core",
            "rows": rows,
            "dates": [item["trade_date"] for item in rows],
            "indices": ["000300.SH"],
        },
        "515880": {
            "role": "transfer",
            "rows": transfer_rows,
            "dates": [item["trade_date"] for item in transfer_rows],
            "indices": ["000300.SH"],
        },
    }

    assert len(rows) > FIRST_EXECUTION
    assert representative_codes(data) == ["510300"]
