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
    truth[2]["oversold_recovery"] = True
    truth[3]["ma60_rising"] = True
    expression = {
        "op": "all",
        "items": [
            {
                "op": "after",
                "first": {"op": "factor", "factor_id": "atr_oversold"},
                "then": {"op": "factor", "factor_id": "oversold_recovery"},
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
    truth[3]["oversold_recovery"] = True
    assert evaluate_expression(expression, truth, 3) is True
    assert render_expression(expression) == "ATR归一化超跌后3日内出现超跌后止跌修复 且 近2日出现MA60 向上 且 非阶段顶部确认"


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
                ("atr_oversold", "oversold_recovery"),
                ("wilder_rsi_oversold", "strong_close"),
                ("ma60_rising", "atr_box_breakout"),
            )
        ],
    }

    assert len(render_expression(expression)) > 100
    assert expression_is_explainable(expression) is False
