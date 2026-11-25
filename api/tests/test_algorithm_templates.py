"""算法模板冻结、因果计算与历史研究对齐。"""

from copy import deepcopy
from datetime import date, timedelta

import pytest

from app.algorithm_templates import (
    prepare_template,
    template_snapshot,
    turning_events,
    turning_profile,
)


def rows(count=180):
    """构造下跌、反弹与回落行情，不依赖本地研究产物。"""
    result = []
    for i in range(count):
        price = 10 - min(i, 70) * .025 + max(0, min(i - 70, 60)) * .07 - max(0, i - 130) * .06
        result.append({"trade_date": str(date(2025, 1, 1) + timedelta(days=i)),
                       **{key: str(price * ratio) for key, ratio in
                          (("open", 1), ("high", 1.01), ("low", .99), ("close", 1))},
                       "volume": "10000"})
    return result


def parameters():
    return {"template": template_snapshot("etf_multifactor", "1.0.0", "510500"),
            "decision_start": "2025-05-01", "external": {}, "slippage_bps": "5"}


def test_template_freezes_internal_rules_and_rejects_injection():
    saved = parameters()
    saved["template"]["rule"]["stop_loss"] = .99
    with pytest.raises(ValueError, match="模板"):
        prepare_template(rows(), [], saved)
    saved = parameters()
    saved["template"]["turning"]["parameters"]["background_days"] = 99
    with pytest.raises(ValueError, match="模板"):
        prepare_template(rows(), [], saved)
    assert parameters()["template"]["rule"]["stop_loss"] == .04
    with pytest.raises(ValueError, match="模板"):
        template_snapshot("etf_multifactor", "unknown", "510500")
    with pytest.raises(ValueError, match="ETF"):
        template_snapshot("etf_multifactor", "1.0.0", "000000")


def test_turning_factor_uses_one_engine_with_etf_bound_parameters():
    large = template_snapshot("range_breakout", "1.0.0", "510310")
    mid = template_snapshot("range_breakout", "1.0.0", "510500")

    assert large["rule"] == mid["rule"]
    assert large["instrument_code"] == "510310"
    assert mid["instrument_code"] == "510500"
    assert large["turning"] == turning_profile("510310")
    assert mid["turning"] == turning_profile("510500")
    assert large["turning"]["parameters"] != mid["turning"]["parameters"]

    history = rows()
    full = turning_events(history, [], mid["turning"]["parameters"])
    for end in (80, 125, 150):
        assert turning_events(history[:end], [], mid["turning"]["parameters"]) == {
            key: kind for key, kind in full.items()
            if key <= history[end - 1]["trade_date"]
        }


def test_prefix_stable_and_model_cost_is_explicit():
    history, settings = rows(), parameters()
    full = prepare_template(history, [], settings)
    turning_events(history, [])
    for end in (80, 125, 150):
        assert turning_events(history[:end], []) == {
            key: kind for key, kind in turning_events(history, []).items()
            if key <= history[end - 1]["trade_date"]}
        assert prepare_template(history[:end], [], deepcopy(settings)) == full[:end]
    assert all(p["decision"].target == 0 for p in full[:120])
    assert full[-1]["indicators"]["model_state_start"] == settings["decision_start"]
    assert "模拟" in full[-1]["indicators"]["model_basis"]


def test_template_registration_uses_the_same_prepare():
    from app.strategies import get_strategy, validate_parameters
    assert get_strategy("algorithm_template")["prepare"] is prepare_template
    validate_parameters("algorithm_template", parameters())
    with pytest.raises(ValueError):
        validate_parameters("algorithm_template", {**parameters(), "rule": {}})


def test_user_configurable_condition_strategy_is_no_longer_registered():
    from app.strategies import get_strategy

    with pytest.raises(ValueError, match="未注册"):
        get_strategy("custom_conditions")


def test_external_snapshot_accepts_only_template_valuation_metrics():
    from app.strategy_inputs import external_snapshot

    class EmptySession:
        def scalars(self, statement):
            return []

    assert external_snapshot(EmptySession(), "510500", [], date(2026, 1, 1)) == {}
    assert external_snapshot(
        EmptySession(), "510500", ["pe_percentile"], date(2026, 1, 1)
    ) == {"pe_percentile": {}}
    with pytest.raises(ValueError, match="估值指标"):
        external_snapshot(None, "510500", ["sentiment"], date(2026, 1, 1))


def test_catalog_algorithms_share_rules_but_freeze_etf_turning_parameters():
    from app.algorithm_templates import template_catalog

    codes = ["510310", "510330", "510500"]
    templates = template_catalog(codes)
    assert [item["id"] for item in templates] == [
        "range_breakout", "bottom_confirmation", "hybrid_reversal", "etf_multifactor",
    ]
    for item in templates[:3]:
        assert item["supported_instruments"] == codes
        snapshots = [template_snapshot(item["id"], item["version"], code) for code in codes]
        assert [snapshot["instrument_code"] for snapshot in snapshots] == codes
        assert snapshots[0]["rule"] == snapshots[1]["rule"] == snapshots[2]["rule"]
        assert snapshots[0]["turning"] == snapshots[1]["turning"]
        assert snapshots[0]["turning"] != snapshots[2]["turning"]
        assert item["turning_profiles_by_instrument"] == {
            code: snapshot["turning"] for code, snapshot in zip(codes, snapshots, strict=True)
        }
        assert snapshots[0]["rule"]["value_metric"] == "none"


def test_multifactor_catalog_exposes_the_rule_used_for_each_supported_etf():
    from app.algorithm_templates import template_catalog

    algorithm = next(item for item in template_catalog(["510310", "510330", "000000"])
                     if item["id"] == "etf_multifactor")
    assert algorithm["supported_instruments"] == ["510310", "510330"]
    rules = algorithm["rules_by_instrument"]
    assert set(rules) == {"510310", "510330"}
    for code, family, valuation in [("510310", "breakout", "pe_percentile"), ("510330", "hybrid", "none")]:
        assert rules[code]["family"] == family
        assert rules[code]["value_metric"] == valuation
        assert rules[code] == template_snapshot(algorithm["id"], algorithm["version"], code)["rule"]


def test_algorithm_backtest_accepts_only_selection_and_dates():
    from pydantic import ValidationError

    from app.strategy_workbench import ComparisonRequest, SaveRequest

    selection = {
        "instrument_code": "510500", "start_date": "2026-08-01", "end_date": "2026-10-01",
        "templates": [{"id": "range_breakout", "version": "1.0.0"}],
    }
    assert ComparisonRequest.model_validate(selection).instrument_code == "510500"
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate({**selection, "initial_cash": 75000})
    with pytest.raises(ValidationError):
        ComparisonRequest.model_validate({**selection, "templates": []})
    assert SaveRequest.model_validate({"comparison_id": 1, "track_key": "template:range_breakout:1.0.0"})
    with pytest.raises(ValidationError):
        SaveRequest.model_validate({"comparison_id": 1, "track_key": "hold", "name": "自定义"})
