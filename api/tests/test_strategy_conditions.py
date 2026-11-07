"""中文条件在历史与盘前共用的因果性、状态机和缺失边界。"""

from copy import deepcopy

import pytest
from test_backtest import bars


def condition(indicator="trend", operator="gt", threshold="0", window=2, **extra):
    return dict(
        indicator=indicator,
        operator=operator,
        threshold=threshold,
        window=window,
        **extra,
    )


def rule(buy=None, sell=None, allocation=100):
    return {
        "buy": {"mode": "all", "conditions": buy or [condition()]},
        "sell": {"mode": "any", "conditions": sell or [condition(operator="lte")]},
        "allocation": allocation,
    }


def test_buy_confirmation_is_not_automatic_exit_and_sell_wins():
    from app.strategy_conditions import prepare_conditions

    rows = bars([10, 8, 10, 11, 10.5, 10.6, 9])
    spec = rule([condition(window=3), condition("momentum", window=2)])
    result = prepare_conditions(rows, [], {"rule": spec})
    assert result[3]["decision"].target == 1
    assert result[4]["decision"].target == 0
    conflict = rule([condition(operator="gte")], [condition(operator="gte")])
    same = prepare_conditions(bars([10, 10, 10]), [], {"rule": conflict})
    assert same[-1]["decision"].target == 0
    assert same[-1]["indicators"]["buy"][0]["satisfied"]
    assert same[-1]["indicators"]["sell"][0]["satisfied"]


def test_causal_values_and_missing_do_not_use_future_or_zero():
    from app.strategy_conditions import prepare_conditions

    rows = bars([10, 12, 11, 13, 12, 15])
    spec = rule(
        [condition("momentum", window=2)], [condition("momentum", "lt", "-5", 2)]
    )
    first = prepare_conditions(rows, [], {"rule": spec})
    changed = deepcopy(rows)
    changed[-1]["close"] = "200"
    second = prepare_conditions(changed, [], {"rule": spec})
    assert first[:-1] == second[:-1]
    external_rule = rule([condition("sentiment", "lt", "20", category_key="wide")])
    external = {"sentiment:wide": {rows[3]["trade_date"]: {"value": "0"}}}
    result = prepare_conditions(rows, [], {"rule": external_rule, "external": external})
    assert result[3]["indicators"]["buy"][0]["value"] == "0"
    assert result[3]["decision"].target == 1
    assert result[4]["decision"] is None
    assert result[4]["indicators"]["buy"][0]["satisfied"] is None


def test_any_group_does_not_hide_unknown_conditions():
    from app.strategy_conditions import prepare_conditions

    spec = rule([condition(), condition("sentiment", category_key="wide")])
    spec["buy"]["mode"] = "any"
    result = prepare_conditions(bars([10, 11, 12]), [], {"rule": spec})
    assert result[-1]["decision"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"allocation": 75},
        {"buy": {"mode": "nested", "conditions": [condition()]}},
        {"sell": {"mode": "any", "conditions": []}},
        {"buy": {"mode": "all", "conditions": [condition("unknown")]}},
        {"buy": {"mode": "all", "conditions": [condition(window=True)]}},
        {"buy": {"mode": "all", "conditions": [condition(threshold="NaN")]}},
        {"buy": {"mode": "all", "conditions": [condition("sentiment")]}},
    ],
)
def test_invalid_rules_are_rejected(patch):
    from app.strategy_conditions import validate_rule

    with pytest.raises(ValueError):
        validate_rule({**rule(), **patch})


def test_volatility_is_percentage_and_zero_is_valid():
    from app.strategy_conditions import prepare_conditions

    spec = rule([condition("volatility", "lte", "0", 2)])
    result = prepare_conditions(bars([10, 10, 10, 10]), [], {"rule": spec})
    assert result[1]["decision"] is None
    assert result[2]["indicators"]["buy"][0]["value"] == "0.0"


def test_decision_start_resets_virtual_position_before_first_execution():
    from app.strategy_conditions import prepare_conditions

    rows = bars([10, 8, 11, 12, 11.9, 11.8, 12])
    spec = rule(
        [condition(window=3), condition("momentum", window=2)],
        [condition(window=3, operator="lt", threshold="-20")],
    )
    result = prepare_conditions(
        rows, [], {"rule": spec, "decision_start": rows[5]["trade_date"]}
    )
    assert result[5]["decision"].target == 0


def test_failed_entry_confirmation_does_not_sell_existing_virtual_position():
    from app.strategy_conditions import prepare_conditions

    spec = rule(
        [condition("momentum", "gt", "0", 2)], [condition("trend", "lt", "-20", 2)]
    )
    result = prepare_conditions(bars([10, 8, 11, 12, 11.9, 11.8]), [], {"rule": spec})
    assert result[2]["decision"].target == 1
    assert not result[-1]["indicators"]["buy"][0]["satisfied"]
    assert result[-1]["decision"].target == 1
    assert result[-1]["decision"].reason == "卖出条件未满足，继续持有"


@pytest.mark.parametrize(
    "item",
    [
        condition(indicator=[]),
        condition(operator=[]),
        {**condition(), "threshold": True},
    ],
)
def test_wrong_condition_types_are_business_validation_errors(item):
    from app.strategy_conditions import validate_rule

    with pytest.raises(ValueError):
        validate_rule(rule([item]))


def test_saved_condition_units_are_explicit_and_cannot_be_reinterpreted():
    from app.strategy_conditions import normalize_rule, validate_rule

    spec = normalize_rule(rule())
    assert spec["buy"]["conditions"][0]["unit"] == "%"
    validate_rule(spec)
    spec["buy"]["conditions"][0]["unit"] = "元"
    with pytest.raises(ValueError):
        validate_rule(spec)
