"""验证滚动研究的选样边界、经济门槛与独立计值区间。"""

from datetime import date, timedelta
from decimal import Decimal

from app.shared_etf_research import RULES
from app.shared_etf_walk_forward import (
    candidates,
    folds,
    neighbors,
    representative_codes,
    trade_stats,
)


def test_representatives_use_only_eligible_training_rows():
    def instrument(volume, training_rows=15, future_volume=1000):
        rows = [
            {
                "trade_date": str(date(2025, 9, 15) + timedelta(days=i)),
                "close": "1",
                "volume": str(volume if i < 16 else future_volume),
            }
            for i in [*range(training_rows), 16, 17]
        ]
        return {"rows": rows, "index": "A"}

    universe = {
        "a": instrument(10),
        "b": instrument(8, future_volume=10000),
        "c": instrument(100, training_rows=12),
    }
    assert representative_codes(
        universe, {code: 1 for code in universe}, "2025-09-01", "2025-10-01"
    ) == ["a"]


def test_quarters_nonoverlap_and_keep_partial_final_period():
    result = list(folds("2026-01-01", "2026-11-16"))
    assert result[0] == ("2025-01-01", "2026-01-01", "2026-04-01")
    assert result[1][1] == result[0][2]
    assert result[-1] == ("2025-10-01", "2026-10-01", "2026-11-17")


def test_adjacent_rules_only_change_one_axis_and_keep_family():
    family = "range_breakout"
    center = RULES[family]
    grid = candidates(family)
    linked = neighbors(center, grid, family)
    assert len(linked) == 8
    assert all(sum(rule[key] != center[key] for key in center) == 1 for rule in linked)


def test_net_expectation_and_pf_do_not_reward_missing_losers():
    assert trade_stats([2.0, 4.0, -3.0, 0.0]) == {
        "completed": 4,
        "wins": 2,
        "win_rate": 0.5,
        "expectancy": 0.75,
        "profit_factor": 2.0,
        "payoff": 1.0,
        "worst_loss": 3.0,
        "tail_ratio": 1.0,
    }
    assert trade_stats([10.0])["profit_factor"] is None
    assert trade_stats([])["expectancy"] is None


def test_selection_rejects_insufficient_trades_and_sharp_peak():
    from app.shared_etf_walk_forward import select_rule

    family = "bottom_reversal"
    grid = candidates(family)
    eligible = {
        **trade_stats([200] * 40 + [-100] * 30),
        "contributing_indices": 4,
        "return": 0.05,
        "drawdown": -0.04,
    }
    sparse = {**eligible, "completed": 11}
    assert select_rule(family, [sparse] * len(grid)) is None
    center = grid.index(RULES[family])
    data = [{**eligible, "return": 0.04} for _ in grid]
    data[center] = {**eligible, "return": 0.13}
    assert select_rule(family, data) != grid[center]
    data[center] = {**eligible, "return": 0.07}
    assert select_rule(family, data) == grid[center]


def test_fold_does_not_trade_outside_interval_or_carry_positions():
    from app.shared_etf_research import prepare_market
    from app.shared_etf_walk_forward import evaluate

    days = [str(date(2025, 1, 1) + timedelta(days=i)) for i in range(130)]
    closes = [10 + i * 0.005 for i in range(120)] + [10.8] * 10
    rows = [
        {
            "trade_date": day,
            "open": str(value),
            "close": str(value),
            "high": str(value + 0.1),
            "low": str(value - 0.2),
            "volume": "1500" if i == 120 else "1000",
        }
        for i, (day, value) in enumerate(zip(days, closes, strict=True))
    ]
    item = {
        "dates": days,
        "rows": rows,
        "market": prepare_market(rows, [], {}),
        "dividends": [],
    }
    first = evaluate(item, days[120], days[124], RULES["range_breakout"])
    assert [row["trade_date"] for row in first["daily"]] == days[120:124]
    assert first["daily"][0]["quantity"] == 0  # 收盘突破，次日才有仓位。
    assert first["daily"][1]["quantity"] > 0
    assert first["open"] == 1 and not first["pnl"]
    second = evaluate(item, days[124], days[129], RULES["range_breakout"])
    assert all(not row["quantity"] for row in second["daily"])


def test_rejects_holdout_before_snapshot_split_cutoff():
    import pytest

    from app.shared_etf_walk_forward import validate_split_cutoffs

    universe = {"a": {"excluded_splits": ["2025-09-12"]}, "b": {"excluded_splits": []}}
    with pytest.raises(ValueError, match="折算"):
        validate_split_cutoffs(universe, "2025-07-01")
    assert validate_split_cutoffs(universe, "2025-10-01") == {"a": ["2025-09-12"]}


def test_training_sample_and_index_breadth_are_separate_from_release():
    from app.shared_etf_walk_forward import economic_checks, select_rule

    family = "bottom_reversal"
    stats = {
        **trade_stats([200.0] * 8 + [-100.0] * 4),
        "return": 0.05,
        "drawdown": -0.02,
    }
    grid = candidates(family)
    assert (
        select_rule(family, [{**stats, "contributing_indices": 3}] * len(grid)) is None
    )
    assert (
        select_rule(family, [{**stats, "contributing_indices": 4}] * len(grid))
        is not None
    )
    assert not economic_checks(stats)["trades"]


def continuous_item(dividends=()):
    from app.shared_etf_research import prepare_market

    days = [str(date(2025, 1, 1) + timedelta(days=i)) for i in range(133)]
    closes = [10 + i * 0.005 for i in range(120)] + [10.8] * 13
    rows = [
        {
            "trade_date": day,
            "open": str(value),
            "close": str(value),
            "high": str(value + 0.1),
            "low": str(value - 0.2),
            "volume": "1500" if i in (120, 129) else "1000",
        }
        for i, (day, value) in enumerate(zip(days, closes, strict=True))
    ]
    return {
        "dates": days,
        "rows": rows,
        "market": prepare_market(rows, dividends, {}),
        "dividends": dividends,
    }


def test_continuous_open_round_uses_entry_rule_and_settles_after_boundary():
    from app.shared_etf_walk_forward import evaluate, fold_summary, portfolio

    item = continuous_item()
    days = item["dates"]
    original = {**RULES["range_breakout"], "timeout": 4}
    later = {**original, "timeout": 100}
    account = evaluate(
        item, days[120], days[132], original, details=True, schedule={days[123]: later}
    )
    buy, sell = account["fills"]
    assert buy["trade_date"] == days[121]
    assert sell["trade_date"] == days[125]  # 以原 4 日规则退出，而非跨季后改为 100 日。
    assert sell["signal_evidence"]["entry_rule"]["timeout"] == 4
    accounts = {"example": account}
    _, _, curve = portfolio(accounts)
    old = fold_summary(accounts, curve, days[120], days[123])
    new = fold_summary(accounts, curve, days[123], days[132])
    assert old["carried_out"] == new["carried_in"] == 1
    assert old["completed"] == 0 and new["completed"] == 1
    assert new["cross_fold_closed"] == 1


def test_new_fold_does_not_rewrite_previous_close_and_applies_at_first_close():
    from app.shared_etf_walk_forward import evaluate

    item = continuous_item()
    days = item["dates"]
    old = RULES["range_breakout"]
    new = {**old, "margin": 100}
    before_switch = evaluate(item, days[120], days[125], old, details=True)
    with_switch = evaluate(
        item, days[120], days[125], old, details=True, schedule={days[121]: new}
    )
    assert with_switch["daily"][0] == before_switch["daily"][0]
    assert with_switch["fills"][0] == before_switch["fills"][0]
    assert with_switch["fills"][0]["trade_date"] == days[121]

    first_close = evaluate(
        item,
        days[120],
        days[125],
        new,
        details=True,
        schedule={days[119]: new, days[120]: old},
    )
    assert first_close["fills"][0]["signal_date"] == days[120]
    assert first_close["fills"][0]["signal_evidence"]["entry_rule"] == old
    first_fold = evaluate(
        item, days[121], days[125], old, details=True, schedule={days[121]: old}
    )
    assert first_fold["daily"][0]["quantity"] == 0
    assert first_fold["fills"] == []


def test_cross_fold_dividend_belongs_to_record_date_holding_even_after_sale():
    from app.shared_etf_walk_forward import evaluate, fold_summary, portfolio

    days = continuous_item()["dates"]
    item = continuous_item(
        [
            {
                "record_date": days[124],
                "ex_date": days[126],
                "pay_date": days[128],
                "cash_per_share": "0.10",
            }
        ]
    )
    rule = {**RULES["range_breakout"], "timeout": 4}
    account = evaluate(
        item, days[120], days[132], rule, details=True, schedule={days[125]: rule}
    )
    buy, sell = account["fills"]
    assert sell["trade_date"] == days[125]
    dividend = Decimal(buy["quantity"]) * Decimal("0.10")
    assert [(event["trade_date"], event["kind"]) for event in account["dividends"]] == [
        (days[126], "receivable"),
        (days[128], "payment"),
    ]
    daily = {row["trade_date"]: row for row in account["daily"]}
    assert Decimal(daily[days[126]]["dividend_receivable"]) == dividend
    assert Decimal(daily[days[128]]["dividend_receivable"]) == 0
    assert daily[days[128]]["equity"] == daily[days[127]]["equity"]
    expected = (
        Decimal(sell["notional"])
        - Decimal(buy["notional"])
        - Decimal(buy["commission"])
        - Decimal(sell["commission"])
        + dividend
    )
    assert Decimal(account["rounds"][0]["pnl"]) == expected
    accounts = {"example": account}
    _, _, curve = portfolio(accounts)
    after = fold_summary(accounts, curve, days[125], days[132])
    assert after["completed"] == after["cross_fold_closed"] == 1
    assert after["expectancy"] == float(expected)
