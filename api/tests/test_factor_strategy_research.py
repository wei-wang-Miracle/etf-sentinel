from datetime import date, timedelta

import pytest

from app.research_factors import FACTORS


def truth_rows(length):
    start = date(2025, 1, 1)
    return [
        {
            "trade_date": str(start + timedelta(days=index)),
            **{factor_id: False for factor_id in FACTORS},
        }
        for index in range(length)
    ]


def price_rows(length):
    start = date(2025, 1, 1)
    return [
        {
            "trade_date": str(start + timedelta(days=index)),
            "open": 10 + index * 0.02,
            "high": 10.15 + index * 0.02,
            "low": 9.9 + index * 0.02,
            "close": 10.05 + index * 0.02,
            "volume": 1000,
        }
        for index in range(length)
    ]


def test_expression_supports_nested_logic_and_past_only_temporal_relations():
    from app.factor_strategy_research import evaluate_expression, render_expression

    truth = truth_rows(5)
    truth[1]["atr_oversold"] = True
    truth[2]["close_above_prior_high"] = True
    truth[3]["ma60_rising"] = True
    expression = {
        "op": "all",
        "items": [
            {
                "op": "after",
                "first": {"op": "factor", "factor_id": "atr_oversold"},
                "then": {"op": "factor", "factor_id": "close_above_prior_high"},
                "days": 3,
            },
            {
                "op": "within",
                "expression": {"op": "factor", "factor_id": "ma60_rising"},
                "days": 2,
            },
            {
                "op": "not",
                "expression": {"op": "factor", "factor_id": "turning_top"},
            },
        ],
    }

    assert evaluate_expression(expression, truth, 2) is False
    assert evaluate_expression(expression, truth, 3) is False
    truth[3]["close_above_prior_high"] = True
    assert evaluate_expression(expression, truth, 3) is True
    assert render_expression(expression) == "ATR归一化超跌后3日内出现收盘收复昨高 且 近2日出现MA60 向上 且 非阶段顶部确认"


def test_expression_renderer_keeps_nested_and_or_precedence_explicit():
    from app.factor_strategy_research import render_expression

    expression = {
        "op": "all",
        "items": [
            {
                "op": "any",
                "items": [
                    {"op": "factor", "factor_id": "atr_oversold"},
                    {"op": "factor", "factor_id": "wilder_rsi_oversold"},
                ],
            },
            {"op": "factor", "factor_id": "strong_close"},
        ],
    }

    assert render_expression(expression) == "（ATR归一化超跌 或 Wilder RSI 超卖） 且 日内强势收盘"


def test_expression_rejects_unknown_factor_identity():
    from app.factor_strategy_research import evaluate_expression

    with pytest.raises(ValueError, match="未登记因子"):
        evaluate_expression(
            {"op": "factor", "factor_id": "invented_factor"}, truth_rows(1), 0
        )


def test_prepare_factor_strategy_uses_entry_day_close_for_next_open_execution():
    from app.factor_strategy_research import RISK_BASELINE, prepare_factor_strategy

    rows = price_rows(75)
    truth = truth_rows(len(rows))
    truth[65]["box_breakout_up"] = True
    truth[68]["turning_top"] = True

    signals = prepare_factor_strategy(
        rows,
        [],
        truth,
        {"op": "factor", "factor_id": "box_breakout_up"},
        {"op": "factor", "factor_id": "turning_top"},
    )

    assert all(item["decision"] is None for item in signals[: RISK_BASELINE["warmup"]])
    assert signals[65]["decision"].target == 1
    assert signals[65]["decision"].reason == "因子入场条件成立"
    assert signals[66]["indicators"]["entry_price"] is not None
    assert signals[68]["decision"].target == 0
    assert signals[68]["decision"].reason == "因子退出条件成立"


def test_candidate_holdout_keeps_position_opened_before_report_window():
    from app.factor_strategy_research import evaluate_candidate

    rows = price_rows(90)
    truth = truth_rows(len(rows))
    truth[65]["box_breakout_up"] = True
    item = {"rows": rows, "actions": {"dividends": []}, "factor_truth": truth}

    result = evaluate_candidate(
        item,
        {"op": "factor", "factor_id": "box_breakout_up"},
        {"op": "factor", "factor_id": "turning_top"},
        start_date=rows[75]["trade_date"],
    )

    assert result["account"]["trades"][0]["trade_date"] == rows[66]["trade_date"]
    assert result["window_start"] == rows[75]["trade_date"]
    assert set(result["benchmark"]) == {"return", "drawdown", "exposure"}


def test_holdout_keeps_carry_position_in_equity_but_excludes_its_full_trade_pnl():
    from app.factor_strategy_research import _window_statistics

    account = {
        "daily": [
            {"trade_date": "2025-02-28", "equity": "50000", "quantity": 100},
            {"trade_date": "2025-03-03", "equity": "51000", "quantity": 0},
            {"trade_date": "2025-03-04", "equity": "51200", "quantity": 0},
        ]
    }
    detail = {
        "rounds": [
            {
                "entry_date": "2025-02-10",
                "exit_date": "2025-03-03",
                "pnl": "1000",
            },
            {
                "entry_date": "2025-03-03",
                "exit_date": "2025-03-04",
                "pnl": "200",
            },
        ],
        "open_rounds": 0,
    }

    window = _window_statistics(account, detail, "2025-03-03")

    assert window["return"] == 0.024
    assert window["completed"] == 1
    assert window["rounds"] == [detail["rounds"][1]]
    assert window["carry_in_completed"] == 1
    assert window["carry_in_rounds"] == [detail["rounds"][0]]


def test_category_leader_is_selected_only_by_development_score():
    from app.factor_strategy_research import select_category_leader

    candidates = [
        {
            "candidate_id": "development_winner",
            "development": {"测试类别": {"score": 8.0}},
            "holdout": {"测试类别": {"score": -2.0}},
        },
        {
            "candidate_id": "holdout_winner",
            "development": {"测试类别": {"score": 3.0}},
            "holdout": {"测试类别": {"score": 20.0}},
        },
    ]

    assert select_category_leader("测试类别", candidates)["candidate_id"] == "development_winner"


def _score_summary(**overrides):
    summary = {
        "completed": 12,
        "win_rate": 0.70,
        "profit_factor": 1.5,
        "expectancy": 500.0,
        "return": 0.1,
        "excess_return": 0.03,
        "drawdown": -0.04,
        "exposure": 0.3,
        "positive_unit_ratio": 1.0,
        "qualified_unit_ratio": 1.0,
    }
    summary.update(overrides)
    return summary


def test_category_score_blocks_low_sample_and_caps_extreme_profit_factor():
    from app.factor_strategy_research import _category_score

    assert _category_score(_score_summary(completed=4, profit_factor=9_000.0)) == 0.0
    assert _category_score(_score_summary(expectancy=-10.0)) == 0.0
    assert _category_score(_score_summary(profit_factor=9_000.0)) == _category_score(
        _score_summary(profit_factor=4.0)
    )
    assert _category_score(_score_summary(excess_return=-0.5)) == _category_score(
        _score_summary(excess_return=0.5)
    )


def test_win_rate_gates_replace_buy_and_hold_outperformance_gate():
    from app.factor_strategy_research import _discard_reasons

    passing = _score_summary(
        excess_return=-0.40,
        drawdown=-0.11,
        independent_units=3,
        cross_unit_pass=True,
    )
    assert _discard_reasons(passing) == []

    low_win_rate = _score_summary(
        win_rate=0.60,
        independent_units=3,
        cross_unit_pass=True,
    )
    assert "胜率低于65%门槛" in _discard_reasons(low_win_rate)

    low_pf = _score_summary(
        profit_factor=1.20,
        independent_units=3,
        cross_unit_pass=True,
    )
    assert "利润因子低于1.25" in _discard_reasons(low_pf)

    deep_dd = _score_summary(
        drawdown=-0.13,
        independent_units=3,
        cross_unit_pass=True,
    )
    assert "最大回撤低于-12%门槛" in _discard_reasons(deep_dd)


def test_profit_factor_without_loss_is_not_rejected_by_profit_factor_gate():
    from app.factor_strategy_research import _discard_reasons

    all_winning = _score_summary(
        completed=8,
        profit_factor=None,
        independent_units=3,
        cross_unit_pass=True,
    )

    assert "利润因子低于1.25" not in _discard_reasons(all_winning)


def test_bear_market_defense_is_reported_without_removing_release_blockers():
    from app.factor_strategy_research import _discard_reasons, defense_evidence

    summary = _score_summary(
        **{
            "return": -0.06,
            "drawdown": -0.1,
            "benchmark_return": -0.24,
            "benchmark_drawdown": -0.3,
            "independent_units": 3,
            "cross_unit_pass": True,
        }
    )

    evidence = defense_evidence(summary)

    assert evidence == {
        "applicable": True,
        "engaged": True,
        "excess_return": 0.18,
        "downside_capture_ratio": 0.25,
        "drawdown_compression_ratio": pytest.approx(1 / 3),
        "qualified": True,
    }
    assert "窗口绝对收益不为正" in _discard_reasons(summary)


def test_bear_market_defense_does_not_treat_staying_out_as_strategy_evidence():
    from app.factor_strategy_research import defense_evidence

    summary = _score_summary(
        **{
            "return": 0.0,
            "drawdown": 0.0,
            "exposure": 0.0,
            "benchmark_return": -0.24,
            "benchmark_drawdown": -0.3,
        }
    )

    evidence = defense_evidence(summary)

    assert evidence["applicable"] is True
    assert evidence["engaged"] is False
    assert evidence["qualified"] is False


def test_category_leader_only_uses_its_own_evolution_pool():
    from app.factor_strategy_research import select_category_leader

    candidates = [
        {
            "candidate_id": "gold_candidate",
            "research_category": "黄金",
            "development": {"黄金": {"score": 3.0}},
        },
        {
            "candidate_id": "communication_candidate",
            "research_category": "通信设备",
            "development": {"黄金": {"score": 999.0}},
        },
    ]

    assert select_category_leader("黄金", candidates)["candidate_id"] == "gold_candidate"


def test_research_runs_three_candidates_per_category_per_round():
    from app.factor_strategy_research import run_research

    rows = price_rows(140)
    universe = {
        "518880": {
            "category": "黄金",
            "independent_key": "518880",
            "rows": rows,
            "actions": {"dividends": []},
            "factor_truth": truth_rows(len(rows)),
        },
        "515880": {
            "category": "通信设备",
            "independent_key": "515880",
            "rows": rows,
            "actions": {"dividends": []},
            "factor_truth": truth_rows(len(rows)),
        },
    }

    for item in universe.values():
        item["factor_truth"][70]["box_breakout_up"] = True
        item["factor_truth"][71]["turning_top"] = True
        item["factor_truth"][72]["ma60_rising"] = True
        item["factor_truth"][73]["strong_close"] = True

    result = run_research(universe, rounds=1)

    assert len(result["candidates"]) == 6
    assert set(result["rounds"][0]["category_candidate_ids"]) == {"黄金", "通信设备"}
    assert all(
        len(candidate_ids) == 3
        for candidate_ids in result["rounds"][0]["category_candidate_ids"].values()
    )
    assert {candidate["research_category"] for candidate in result["candidates"]} == {
        "黄金",
        "通信设备",
    }
    assert all(
        set(candidate["development"]) == {candidate["research_category"]}
        for candidate in result["candidates"]
    )


def test_category_summary_labels_single_independent_unit_as_single_instrument_evidence():
    from app.factor_strategy_research import summarize_category

    universe = {
        "518880": {
            "category": "黄金",
            "independent_key": "518880",
        }
    }
    evaluations = {
        "518880": {
            "rounds": [{"pnl": "100"}, {"pnl": "-50"}],
            "carry_in_rounds": [],
            "carry_in_completed": 0,
            "return": 0.04,
            "drawdown": -0.02,
            "exposure": 0.3,
            "completed": 2,
            "open": 0,
            "benchmark": {"return": 0.01, "drawdown": -0.03},
        }
    }

    summary = summarize_category("黄金", universe, evaluations)

    assert summary["evidence_level"] == "单标的证据"
    assert summary["cross_unit_pass"] is None
    assert summary["independent_units"] == 1
    assert summary["completed"] == 2
    assert summary["benchmark_return"] == 0.01
    assert summary["excess_return"] == 0.03


def test_prepare_factor_strategy_validates_each_expression_once(monkeypatch):
    import app.factor_strategy_research as research

    rows = price_rows(75)
    truth = truth_rows(len(rows))
    entry = {"op": "factor", "factor_id": "box_breakout_up"}
    exit_expression = {"op": "factor", "factor_id": "turning_top"}
    calls = 0
    original = research.validate_expression

    def counting_validate(expression):
        nonlocal calls
        calls += 1
        return original(expression)

    monkeypatch.setattr(research, "validate_expression", counting_validate)

    research.prepare_factor_strategy(rows, [], truth, entry, exit_expression)

    assert calls == 2


def test_expression_simplification_removes_equivalent_repetition_before_selection():
    from app.factor_strategy_research import (
        expression_is_explainable,
        simplify_expression,
    )

    expression = {
        "op": "all",
        "items": [
            {"op": "factor", "factor_id": "ma60_rising"},
            {
                "op": "all",
                "items": [
                    {"op": "factor", "factor_id": "ma60_rising"},
                    {"op": "factor", "factor_id": "strong_close"},
                ],
            },
            {"op": "not", "expression": {"op": "not", "expression": {"op": "factor", "factor_id": "strong_close"}}},
        ],
    }

    simplified = simplify_expression(expression)

    assert simplified == {
        "op": "all",
        "items": [
            {"op": "factor", "factor_id": "ma60_rising"},
            {"op": "factor", "factor_id": "strong_close"},
        ],
    }
    assert expression_is_explainable(simplified) is True


def test_expression_explainability_requires_one_screen_chinese_description():
    from app.factor_strategy_research import (
        expression_is_explainable,
        render_expression,
    )

    expression = {
        "op": "any",
        "items": [
            {
                "op": "after",
                "first": {"op": "factor", "factor_id": first},
                "then": {"op": "factor", "factor_id": second},
                "days": 8,
            }
            for first, second in (
                ("turning_bottom", "ma5_cross_ma20_up"),
                ("box_breakout_up", "volume_breakout_up"),
                ("atr_oversold", "close_above_prior_high"),
                ("wilder_rsi_oversold", "strong_close"),
                ("ma60_rising", "atr_box_breakout"),
            )
        ],
    }

    assert len(render_expression(expression)) > 100
    assert expression_is_explainable(expression) is False


def test_anti_cheat_expression_rules_block_not_event_consecutive_and_nesting():
    from app.factor_strategy_research import (
        expression_is_explainable,
        holdout_start_date,
    )

    root_not = {"op": "not", "expression": {"op": "factor", "factor_id": "turning_top"}}
    assert expression_is_explainable(root_not, role="entry") is False
    assert expression_is_explainable(root_not, role="exit") is False

    any_with_not = {
        "op": "any",
        "items": [
            {"op": "factor", "factor_id": "box_breakout_up"},
            {"op": "not", "expression": {"op": "factor", "factor_id": "turning_top"}},
        ],
    }
    assert expression_is_explainable(any_with_not, role="entry") is False

    all_with_local_not = {
        "op": "all",
        "items": [
            {"op": "factor", "factor_id": "box_breakout_up"},
            {"op": "not", "expression": {"op": "factor", "factor_id": "atr_oversold"}},
        ],
    }
    assert expression_is_explainable(all_with_local_not, role="entry") is True

    assert expression_is_explainable(
        {"op": "factor", "factor_id": "close_above_prior_high"}, role="exit"
    ) is False
    assert expression_is_explainable(
        {"op": "factor", "factor_id": "turning_top"}, role="entry"
    ) is False

    event_consecutive = {
        "op": "consecutive",
        "expression": {"op": "factor", "factor_id": "turning_top"},
        "days": 5,
    }
    assert expression_is_explainable(event_consecutive, role="exit") is False

    state_consecutive = {
        "op": "consecutive",
        "expression": {"op": "factor", "factor_id": "ma60_rising"},
        "days": 3,
    }
    assert expression_is_explainable(state_consecutive, role="entry") is True

    nested_within = {
        "op": "within",
        "expression": {
            "op": "within",
            "expression": {"op": "factor", "factor_id": "turning_bottom"},
            "days": 3,
        },
        "days": 5,
    }
    assert expression_is_explainable(nested_within, role="entry") is False

    long_rows = price_rows(1900)
    short_rows = long_rows[-350:]
    holdout = holdout_start_date(
        {
            "510300": {"rows": long_rows},
            "510500": {"rows": long_rows},
            "159205": {"rows": short_rows},
        }
    )
    # 留出段应按多年度长序列的最后 20% 切分，而不是被 350 根的新标的拖成 60 天
    assert holdout == long_rows[-round((1900 - 66) * 0.2)]["trade_date"]


def test_category_factor_pool_only_contains_development_truths():
    from app.factor_strategy_research import category_factor_ids

    rows = price_rows(80)
    truth = truth_rows(len(rows))
    truth[66]["box_breakout_up"] = True
    universe = {
        "510300": {
            "category": "沪深300",
            "rows": rows,
            "factor_truth": truth,
        }
    }

    assert category_factor_ids("沪深300", universe, rows[70]["trade_date"]) == {
        "box_breakout_up"
    }


def test_release_gate_reasons_merge_normal_and_stress_cost_windows():
    from app.factor_strategy_research import release_gate_reasons

    normal = _score_summary(independent_units=3, cross_unit_pass=True)
    development_stress = _score_summary(
        independent_units=3,
        cross_unit_pass=True,
        profit_factor=1.2,
    )
    holdout = _score_summary(independent_units=3, cross_unit_pass=True)
    holdout_stress = _score_summary(independent_units=3, cross_unit_pass=True)

    assert release_gate_reasons(
        development=normal,
        development_stress=development_stress,
        holdout=holdout,
        holdout_stress=holdout_stress,
    ) == ["开发段压力成本：利润因子低于1.25"]
