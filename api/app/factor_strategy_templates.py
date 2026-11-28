"""基于因子表达式的通用与分类策略模板，按研究门禁结果决定是否开放采用。"""

from datetime import date
from math import isfinite

from app.algorithm_templates import TURNING_VERSION, turning_events, turning_profile
from app.factor_strategy_research import RISK_BASELINE, prepare_factor_strategy
from app.research_factor_context import build_external_factor_truth
from app.research_factors import STRATEGIES, factor_truth_rows

FACTOR_STRATEGY_VERSION = "factor-strategy-template-v1.0.0"

FACTOR_TEMPLATES = {
    "trend_pullback": {
        "min_warmup_bars": 250,
        "external_requirements": (),
        "risk_baseline": dict(RISK_BASELINE),
        "entry_expression": {
            "op": "all",
            "items": [
                {"op": "factor", "factor_id": "above_ma250"},
                {"op": "factor", "factor_id": "adx_trending"},
                {"op": "factor", "factor_id": "trend_pullback_near_ma20"},
            ],
        },
        "exit_expression": {
            "op": "any",
            "items": [
                {"op": "factor", "factor_id": "turning_top"},
                {"op": "factor", "factor_id": "adx_choppy"},
                {"op": "factor", "factor_id": "atr_overbought"},
            ],
        },
    },
    "volatility_contraction_breakout": {
        "min_warmup_bars": 66,
        "external_requirements": (),
        "risk_baseline": dict(RISK_BASELINE),
        "entry_expression": {
            "op": "all",
            "items": [
                {
                    "op": "within",
                    "days": 5,
                    "expression": {
                        "op": "factor",
                        "factor_id": "volatility_contracting",
                    },
                },
                {"op": "factor", "factor_id": "atr_box_breakout"},
                {"op": "factor", "factor_id": "strong_close"},
            ],
        },
        "exit_expression": {
            "op": "any",
            "items": [
                {"op": "factor", "factor_id": "turning_top"},
                {"op": "factor", "factor_id": "high_volume_stall"},
                {"op": "factor", "factor_id": "close_cross_ma10_down"},
            ],
        },
    },
    "value_sentiment_reversal": {
        "min_warmup_bars": 66,
        "external_requirements": ("valuation", "market_fear_greed"),
        "risk_baseline": {**RISK_BASELINE, "weak_exit_days": 40},
        "entry_expression": {
            "op": "all",
            "items": [
                {
                    "op": "any",
                    "items": [
                        {"op": "factor", "factor_id": "erp_high_percentile"},
                        {"op": "factor", "factor_id": "dividend_yield_high"},
                        {"op": "factor", "factor_id": "valuation_low_percentile"},
                        {
                            "op": "within",
                            "days": 5,
                            "expression": {
                                "op": "factor",
                                "factor_id": "market_fear_extreme",
                            },
                        },
                    ],
                },
                {"op": "factor", "factor_id": "oversold_recovery"},
            ],
        },
        "exit_expression": {
            "op": "any",
            "items": [
                {"op": "factor", "factor_id": "turning_top"},
                {"op": "factor", "factor_id": "valuation_high_percentile"},
                {"op": "factor", "factor_id": "market_greed_extreme"},
                {"op": "factor", "factor_id": "wilder_rsi_overbought_turn_down"},
            ],
        },
    },
    "gem_bottom_contraction": {
        "min_warmup_bars": 66,
        "external_requirements": ("market_fear_greed",),
        "risk_baseline": dict(RISK_BASELINE),
        "entry_expression": {
            "op": "all",
            "items": [
                {
                    "op": "within",
                    "days": 5,
                    "expression": {"op": "factor", "factor_id": "turning_bottom"},
                },
                {
                    "op": "within",
                    "days": 3,
                    "expression": {
                        "op": "factor",
                        "factor_id": "volatility_contracting",
                    },
                },
                {"op": "factor", "factor_id": "strong_close"},
                {"op": "factor", "factor_id": "close_position_positive"},
            ],
        },
        "exit_expression": {
            "op": "all",
            "items": [
                {"op": "factor", "factor_id": "ma5_cross_ma20_down"},
                {
                    "op": "not",
                    "expression": {
                        "op": "factor",
                        "factor_id": "market_greed_extreme",
                    },
                },
            ],
        },
    },
}


def is_factor_template(strategy_id):
    """判断策略身份是否属于基于因子表达式的新型比较模板。"""
    return strategy_id in FACTOR_TEMPLATES


def factor_template_snapshot(strategy_id, instrument_code):
    """构造单只 ETF 对应新因子策略的不可变规则快照。"""
    spec = FACTOR_TEMPLATES.get(strategy_id)
    definition = STRATEGIES.get(strategy_id)
    if spec is None or definition is None:
        raise ValueError("因子策略模板不存在")
    if instrument_code is None:
        raise ValueError("因子策略模板必须指定ETF")
    return {
        "id": strategy_id,
        "version": FACTOR_STRATEGY_VERSION,
        "name": definition["name"],
        "description": definition["description"],
        "instrument_code": instrument_code,
        "adoptable": definition.get("adoptable", True),
        "turning_version": TURNING_VERSION,
        "turning": turning_profile(instrument_code),
        "min_warmup_bars": spec["min_warmup_bars"],
        "external_requirements": list(spec["external_requirements"]),
        "risk_baseline": dict(spec["risk_baseline"]),
        "entry_expression": spec["entry_expression"],
        "exit_expression": spec["exit_expression"],
    }


def validate_factor_template_parameters(parameters):
    """核验执行参数与代码内冻结因子策略模板一致，拒绝外部注入规则。"""
    if not isinstance(parameters, dict) or set(parameters) != {
        "template",
        "decision_start",
        "external",
        "slippage_bps",
    }:
        raise ValueError("因子策略参数无效")
    snapshot = parameters["template"]
    if not isinstance(snapshot, dict):
        raise ValueError("因子策略快照无效")  # noqa: TRY004 — 统一转换为输入校验异常
    expected = factor_template_snapshot(
        snapshot.get("id"), snapshot.get("instrument_code")
    )
    if snapshot != expected:
        raise ValueError("因子策略快照与冻结版本不一致")
    try:
        date.fromisoformat(parameters["decision_start"])
        slippage = float(parameters["slippage_bps"])
    except (TypeError, ValueError):
        raise ValueError("因子策略输入日期或滑点无效") from None
    if not isfinite(slippage) or not 0 <= slippage <= 100:
        raise ValueError("因子策略滑点须为0至100基点")
    if not isinstance(parameters["external"], dict):
        raise ValueError("因子策略外部数据快照无效")  # noqa: TRY004 — 统一转换为输入校验异常


def prepare_factor_template(rows, dividends, parameters):
    """基于回测快照内的行情、权益及外部上下文因果生成逐日策略决策。

    若外部快照附带已标准化份额的 ``warmup_rows``（跨折算全历史预热序列），
    则在全历史序列上计算均线/因子与 ATR 预热，再将逐日决策精确切回当前拆后 ``rows``。
    """
    validate_factor_template_parameters(parameters)
    template = parameters["template"]
    external = parameters["external"]
    warmup_rows = external.get("warmup_rows")
    if warmup_rows:
        if len(warmup_rows) < len(rows) or [
            row["trade_date"] for row in warmup_rows[-len(rows) :]
        ] != [row["trade_date"] for row in rows]:
            raise ValueError("跨折算预热行情与回测行情末尾日期不一致")
        calc_rows = warmup_rows
        calc_dividends = external.get("warmup_dividends")
        if calc_dividends is None:
            calc_dividends = dividends
    else:
        calc_rows = rows
        calc_dividends = dividends
    turning = turning_events(
        calc_rows, calc_dividends, template["turning"]["parameters"]
    )
    external_truth, _ = build_external_factor_truth(
        calc_rows,
        valuation_rows=external.get("valuation_rows") or (),
        market_rows=external.get("market_rows") or (),
    )
    truth_rows = factor_truth_rows(
        calc_rows,
        turning,
        calc_dividends,
        external_truth=external_truth,
    )
    decision_start_idx = next(
        (
            index
            for index, row in enumerate(calc_rows)
            if row["trade_date"] >= parameters["decision_start"]
        ),
        len(calc_rows),
    )
    start_index = max(template["min_warmup_bars"] - 1, decision_start_idx)
    decisions = prepare_factor_strategy(
        calc_rows,
        calc_dividends,
        truth_rows,
        template["entry_expression"],
        template["exit_expression"],
        costs={"slippage_bps": parameters["slippage_bps"]},
        risk_baseline=template["risk_baseline"],
        start_index=start_index,
    )
    return decisions[-len(rows) :]
