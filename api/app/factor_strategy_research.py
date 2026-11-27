"""冻结输入上的可解释因子组合研究，不注册或发布生产策略。"""

import json
import random
from bisect import bisect_left
from collections import defaultdict
from decimal import Decimal
from statistics import fmean

from app.backtest import simulate
from app.indicators import wilder14
from app.research_factors import FACTORS
from app.strategies import Decision, features
from app.strategy_research import diagnostics

RISK_BASELINE = {
    "warmup": 65,
    "max_stop": 0.07,
    "initial_stop_atr": 2.0,
    "trail_start_atr": 2.5,
    "trail_atr": 2.5,
    "tighten_atr": 5.0,
    "tight_trail_atr": 1.8,
    "weak_exit_days": 18,
    "weak_gain_atr": 1.0,
}
COSTS = {
    "initial_cash": 50_000,
    "commission_rate": 0.0001,
    "minimum_commission": 0,
    "slippage_bps": 5,
}
STRESS_COSTS = {
    **COSTS,
    "commission_rate": 0.0003,
    "minimum_commission": 5,
    "slippage_bps": 10,
}
RESEARCH_VERSION = "factor-strategy-research-v1.1.0"
HOLDOUT_RATIO = 0.2
MIN_HOLDOUT_DAYS = 60
MIN_COMPLETED_TRADES = 5
MAX_SCORE_PROFIT_FACTOR = 4.0
BEARISH_BENCHMARK_RETURN = -0.05
MAX_DOWNSIDE_CAPTURE_RATIO = 0.5
MAX_DRAWDOWN_COMPRESSION_RATIO = 0.5
MAX_DRAWDOWN = -0.08
MIN_PROFIT_FACTOR = 1.1
MAX_EXPLANATION_CHARS = 100


def _positive_days(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_expression(expression):
    """验证策略表达式只引用因子目录中的可观察身份。"""
    if not isinstance(expression, dict) or not isinstance(expression.get("op"), str):
        raise TypeError("策略表达式须为带操作符的对象")
    operator = expression["op"]
    if operator == "factor":
        if set(expression) != {"op", "factor_id"}:
            raise ValueError("因子表达式字段无效")
        if expression["factor_id"] not in FACTORS:
            raise ValueError("引用了未登记因子")
    elif operator in {"all", "any"}:
        if set(expression) != {"op", "items"} or not isinstance(expression["items"], list):
            raise ValueError("组合表达式字段无效")
        if len(expression["items"]) < 2:
            raise ValueError("组合表达式至少需要两个子条件")
        for item in expression["items"]:
            validate_expression(item)
    elif operator == "not":
        if set(expression) != {"op", "expression"}:
            raise ValueError("非表达式字段无效")
        validate_expression(expression["expression"])
    elif operator in {"within", "consecutive"}:
        if set(expression) != {"op", "expression", "days"} or not _positive_days(
            expression["days"]
        ):
            raise ValueError("时间表达式字段无效")
        validate_expression(expression["expression"])
    elif operator == "after":
        if set(expression) != {"op", "first", "then", "days"} or not _positive_days(
            expression["days"]
        ):
            raise ValueError("先后表达式字段无效")
        validate_expression(expression["first"])
        validate_expression(expression["then"])
    else:
        raise ValueError("策略表达式操作符无效")


def expression_factor_ids(expression):
    """返回表达式引用的因子身份，供冻结结果复核。"""
    validate_expression(expression)
    return _expression_factor_ids(expression)


def _expression_factor_ids(expression):
    operator = expression["op"]
    if operator == "factor":
        return {expression["factor_id"]}
    if operator in {"all", "any"}:
        return set().union(*(_expression_factor_ids(item) for item in expression["items"]))
    if operator in {"not", "within", "consecutive"}:
        return _expression_factor_ids(expression["expression"])
    return _expression_factor_ids(expression["first"]) | _expression_factor_ids(
        expression["then"]
    )


def render_expression(expression):
    """将策略表达式渲染成用户可读的中文说明。"""
    validate_expression(expression)
    return _render_expression(expression)


def _render_expression(expression, parent_operator=None):
    operator = expression["op"]
    if operator == "factor":
        return FACTORS[expression["factor_id"]]["name"]
    if operator == "all":
        text = " 且 ".join(
            _render_expression(item, operator) for item in expression["items"]
        )
        return f"（{text}）" if parent_operator == "any" else text
    if operator == "any":
        text = " 或 ".join(
            _render_expression(item, operator) for item in expression["items"]
        )
        return f"（{text}）" if parent_operator == "all" else text
    if operator == "not":
        child = expression["expression"]
        text = _render_expression(child)
        return f"非（{text}）" if child["op"] in {"all", "any"} else f"非{text}"
    if operator == "within":
        child = expression["expression"]
        text = _render_expression(child)
        return (
            f"近{expression['days']}日出现（{text}）"
            if child["op"] in {"all", "any"}
            else f"近{expression['days']}日出现{text}"
        )
    if operator == "consecutive":
        child = expression["expression"]
        text = _render_expression(child)
        return (
            f"连续{expression['days']}日满足（{text}）"
            if child["op"] in {"all", "any"}
            else f"连续{expression['days']}日满足{text}"
        )
    first, then = expression["first"], expression["then"]
    first_text, then_text = _render_expression(first), _render_expression(then)
    return (
        f"{'（' + first_text + '）' if first['op'] in {'all', 'any'} else first_text}"
        f"后{expression['days']}日内出现"
        f"{'（' + then_text + '）' if then['op'] in {'all', 'any'} else then_text}"
    )


def _evaluate(expression, truth_rows, index):
    operator = expression["op"]
    if operator == "factor":
        return bool(truth_rows[index][expression["factor_id"]])
    if operator == "all":
        return all(_evaluate(item, truth_rows, index) for item in expression["items"])
    if operator == "any":
        return any(_evaluate(item, truth_rows, index) for item in expression["items"])
    if operator == "not":
        return not _evaluate(expression["expression"], truth_rows, index)
    if operator == "within":
        return any(
            _evaluate(expression["expression"], truth_rows, prior)
            for prior in range(max(0, index - expression["days"] + 1), index + 1)
        )
    if operator == "consecutive":
        return index + 1 >= expression["days"] and all(
            _evaluate(expression["expression"], truth_rows, prior)
            for prior in range(index - expression["days"] + 1, index + 1)
        )
    return _evaluate(expression["then"], truth_rows, index) and any(
        _evaluate(expression["first"], truth_rows, prior)
        for prior in range(max(0, index - expression["days"]), index)
    )


def _expression_truth(expression, truth_rows):
    operator = expression["op"]
    if operator == "factor":
        return [bool(row[expression["factor_id"]]) for row in truth_rows]
    if operator in {"all", "any"}:
        children = [_expression_truth(item, truth_rows) for item in expression["items"]]
        reducer = all if operator == "all" else any
        return [reducer(values) for values in zip(*children, strict=True)]
    if operator == "not":
        return [not value for value in _expression_truth(expression["expression"], truth_rows)]
    if operator == "within":
        result, active = [], []
        for index, value in enumerate(_expression_truth(expression["expression"], truth_rows)):
            active.append(index if value else None)
            cutoff = index - expression["days"] + 1
            active = [item for item in active if item is not None and item >= cutoff]
            result.append(bool(active))
        return result
    if operator == "consecutive":
        streak, result = 0, []
        for value in _expression_truth(expression["expression"], truth_rows):
            streak = streak + 1 if value else 0
            result.append(streak >= expression["days"])
        return result
    first = _expression_truth(expression["first"], truth_rows)
    then = _expression_truth(expression["then"], truth_rows)
    last_seen, result = None, []
    for index, value in enumerate(then):
        result.append(
            bool(value and last_seen is not None and last_seen >= index - expression["days"])
        )
        if first[index]:
            last_seen = index
    return result


def evaluate_expression(expression, truth_rows, index):
    """在某一交易日计算表达式；时间算子绝不读取后续因子真值。"""
    validate_expression(expression)
    if not 0 <= index < len(truth_rows):
        raise ValueError("表达式计算日期超出因子序列")
    return _expression_truth(expression, truth_rows)[index]


def _adjusted_bars(rows, dividends):
    values = [float(value) for value, _ in features(rows, dividends, 2)]
    scales = [
        value / float(row["close"]) for value, row in zip(values, rows, strict=True)
    ]
    atrs, atr = [], 0.0
    gain = loss = 0.0
    for index, row in enumerate(rows):
        previous = values[index - 1] if index else values[index]
        atr, gain, loss = wilder14(
            previous,
            values[index],
            float(row["high"]) * scales[index],
            float(row["low"]) * scales[index],
            index,
            atr,
            gain,
            loss,
        )
        atrs.append(atr)
    return scales, atrs


def prepare_factor_strategy(
    rows,
    dividends,
    truth_rows,
    entry_expression,
    exit_expression,
    *,
    costs=COSTS,
):
    """以既有因子表达式生成次日开盘执行的统一风险基线决策。"""
    validate_expression(entry_expression)
    validate_expression(exit_expression)
    if len(rows) != len(truth_rows) or any(
        row["trade_date"] != truth["trade_date"]
        for row, truth in zip(rows, truth_rows, strict=True)
    ):
        raise ValueError("行情与因子真值日期不一致")

    scales, atrs = _adjusted_bars(rows, dividends)
    records = {event["record_date"]: event for event in dividends}
    ex_dates = {event["ex_date"]: event for event in dividends}
    slippage = Decimal(str(costs["slippage_bps"])) / 10000
    entry_text = _render_expression(entry_expression)
    exit_text = _render_expression(exit_expression)
    entry_factors = sorted(_expression_factor_ids(entry_expression))
    exit_factors = sorted(_expression_factor_ids(exit_expression))
    entry_truth = _expression_truth(entry_expression, truth_rows)
    exit_truth = _expression_truth(exit_expression, truth_rows)
    target, entry, last_exit = 0, None, -10_000
    result = []
    for index, row in enumerate(rows):
        trace = {
            "preheated": index >= RISK_BASELINE["warmup"],
            "entry_expression": entry_text,
            "exit_expression": exit_text,
            "entry_factors": entry_factors,
            "exit_factors": exit_factors,
        }
        if index < RISK_BASELINE["warmup"]:
            result.append({"decision": None, "indicators": trace})
            continue

        day = row["trade_date"]
        if target and entry is None:
            signal_atr = atrs[index - 1] / scales[index - 1]
            price = float(
                (Decimal(str(row["open"])) * (1 + slippage) * 1000).to_integral_value(
                    rounding="ROUND_CEILING"
                )
                / 1000
            )
            initial_stop = price - min(
                RISK_BASELINE["max_stop"] * price,
                RISK_BASELINE["initial_stop_atr"] * signal_atr,
            )
            entry = {
                "index": index,
                "price": price,
                "atr": signal_atr,
                "initial_stop": initial_stop,
                "protection": initial_stop,
                "peak": price,
                "credited": 0.0,
                "owned": set(),
            }
        elif not target and entry is not None:
            entry, last_exit = None, index

        entry_active = entry_truth[index]
        if entry is None:
            target = int(entry_active)
            reason = "因子入场条件成立" if target else "等待因子入场条件"
            trace.update(entry_match=entry_active, cooldown=index - last_exit > 0)
        else:
            if event := records.get(day):
                entry["owned"].add(event["ex_date"])
            if day in entry["owned"]:
                entry["credited"] += float(ex_dates[day]["cash_per_share"])
            effective = float(row["close"]) + entry["credited"]
            entry["peak"] = max(entry["peak"], effective)
            reasons = []
            gain = entry["peak"] - entry["price"]
            if gain >= RISK_BASELINE["trail_start_atr"] * entry["atr"]:
                multiplier = (
                    RISK_BASELINE["tight_trail_atr"]
                    if gain >= RISK_BASELINE["tighten_atr"] * entry["atr"]
                    else RISK_BASELINE["trail_atr"]
                )
                entry["protection"] = max(
                    entry["protection"],
                    entry["price"],
                    entry["peak"] - multiplier * atrs[index] / scales[index],
                )
            exit_active = exit_truth[index]
            if exit_active:
                reasons.append("因子退出条件成立")
            if effective <= entry["protection"]:
                reasons.append(
                    "ATR移动退出"
                    if entry["protection"] > entry["initial_stop"]
                    else "ATR初始止损"
                )
            if (
                index - entry["index"] + 1 >= RISK_BASELINE["weak_exit_days"]
                and effective - entry["price"]
                < RISK_BASELINE["weak_gain_atr"] * entry["atr"]
            ):
                reasons.append("弱势时间退出")
            target = int(not reasons)
            reason = "、".join(reasons) if reasons else "继续持有"
            trace.update(
                entry_match=entry_active,
                exit_match=exit_active,
                entry_price=entry["price"],
                entry_atr=entry["atr"],
                protection=entry["protection"],
                peak=entry["peak"],
            )
        result.append({"decision": Decision(target, reason), "indicators": trace})
    return result


def _window_statistics(account, detail, start_day):
    daily = account["daily"]
    report_daily = [row for row in daily if row["trade_date"] >= start_day]
    baseline = Decimal(report_daily[0]["equity"])
    prior = [row for row in daily if row["trade_date"] < start_day]
    if prior:
        baseline = Decimal(prior[-1]["equity"])
    peak, drawdown = baseline, Decimal(0)
    for row in report_daily:
        equity = Decimal(row["equity"])
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    rounds = [
        round_item
        for round_item in detail["rounds"]
        if round_item["entry_date"] >= start_day
    ]
    carry_in_rounds = [
        round_item
        for round_item in detail["rounds"]
        if round_item["entry_date"] < start_day <= round_item["exit_date"]
    ]
    return {
        "rounds": rounds,
        "carry_in_rounds": carry_in_rounds,
        "carry_in_completed": len(carry_in_rounds),
        "open": detail["open_rounds"],
        "completed": len(rounds),
        "return": float(Decimal(report_daily[-1]["equity"]) / baseline - 1),
        "drawdown": float(drawdown),
        "exposure": sum(row["quantity"] > 0 for row in report_daily) / len(report_daily),
        "window_start": start_day,
        "window_end": report_daily[-1]["trade_date"],
    }


def evaluate_candidate(
    item,
    entry_expression,
    exit_expression,
    *,
    start_date=None,
    stop_date=None,
    costs=COSTS,
):
    """在一只冻结 ETF 的指定时间段结算候选，含完整交易统计。"""
    rows, dividends, truth_rows = (
        item["rows"],
        item["actions"]["dividends"],
        item["factor_truth"],
    )
    dates = [row["trade_date"] for row in rows]
    begin = RISK_BASELINE["warmup"] + 1
    report_begin = max(begin, bisect_left(dates, start_date) if start_date else begin)
    end = bisect_left(dates, stop_date) if stop_date else len(rows)
    if report_begin >= end:
        return None
    signals = prepare_factor_strategy(
        rows, dividends, truth_rows, entry_expression, exit_expression, costs=costs
    )
    account = simulate(
        rows,
        dividends,
        {**costs, "end_date": dates[end - 1]},
        signals,
        begin,
    )
    detail = diagnostics(
        account,
        dividend_record_dates={
            event["ex_date"]: event["record_date"] for event in dividends
        },
    )
    benchmark = simulate(
        rows,
        dividends,
        {**costs, "end_date": dates[end - 1]},
        signals,
        begin,
        benchmark=True,
    )
    benchmark_detail = diagnostics(
        benchmark,
        dividend_record_dates={
            event["ex_date"]: event["record_date"] for event in dividends
        },
    )
    window = _window_statistics(account, detail, dates[report_begin])
    benchmark_window = _window_statistics(
        benchmark, benchmark_detail, dates[report_begin]
    )
    return {
        "account": account,
        "signals": signals,
        **window,
        "benchmark": {
            key: benchmark_window[key] for key in ("return", "drawdown", "exposure")
        },
    }


def _pnl_statistics(rounds):
    pnl = [float(item["pnl"]) for item in rounds]
    wins = [value for value in pnl if value > 0]
    losses = [-value for value in pnl if value < 0]
    return {
        "completed": len(pnl),
        "expectancy": fmean(pnl) if pnl else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "win_rate": len(wins) / len(pnl) if pnl else None,
        "worst_loss": max(losses, default=0.0),
    }


def _compact_evaluation(result):
    return {
        key: result[key]
        for key in (
            "rounds",
            "carry_in_rounds",
            "carry_in_completed",
            "open",
            "completed",
            "return",
            "drawdown",
            "exposure",
            "window_start",
            "window_end",
            "benchmark",
        )
    }


def evaluate_universe(
    universe, entry_expression, exit_expression, *, start_date=None, stop_date=None, costs=COSTS
):
    """对冻结内所有 ETF 结算同一候选，并删除无关的日频大对象。"""
    result = {}
    for code, item in sorted(universe.items()):
        evaluation = evaluate_candidate(
            item,
            entry_expression,
            exit_expression,
            start_date=start_date,
            stop_date=stop_date,
            costs=costs,
        )
        if evaluation is not None:
            result[code] = _compact_evaluation(evaluation)
    return result


def _unit_summary(code_results):
    rounds = [round_item for result in code_results.values() for round_item in result["rounds"]]
    carry_in_rounds = [
        round_item for result in code_results.values() for round_item in result["carry_in_rounds"]
    ]
    stats = _pnl_statistics(rounds)
    return {
        **stats,
        "carry_in_completed": len(carry_in_rounds),
        "return": fmean(result["return"] for result in code_results.values()),
        "drawdown": min(result["drawdown"] for result in code_results.values()),
        "exposure": fmean(result["exposure"] for result in code_results.values()),
        "open": sum(result["open"] for result in code_results.values()),
        "benchmark_return": fmean(
            result["benchmark"]["return"] for result in code_results.values()
        ),
        "benchmark_drawdown": min(
            result["benchmark"]["drawdown"] for result in code_results.values()
        ),
        "codes": sorted(code_results),
    }


def _category_score(summary):
    if summary["completed"] < MIN_COMPLETED_TRADES:
        return 0.0
    expectancy = (summary["expectancy"] or 0.0) / COSTS["initial_cash"]
    profit_factor = summary["profit_factor"]
    if profit_factor is None:
        profit_factor = MAX_SCORE_PROFIT_FACTOR
    else:
        profit_factor = min(profit_factor, MAX_SCORE_PROFIT_FACTOR)
    sample_weight = min(1.0, summary["completed"] / 12)
    return round(
        (
            summary["return"] * 100
            + summary["excess_return"] * 75
            + (profit_factor - 1) * 5
            + expectancy * 100
            - abs(summary["drawdown"]) * 25
        )
        * (0.5 + sample_weight / 2)
        * summary["positive_unit_ratio"],
        6,
    )


def defense_evidence(summary):
    """仅描述下跌留出段的相对防守，不参与任何发布资格判断。"""
    benchmark_return = summary["benchmark_return"]
    excess_return = summary["return"] - benchmark_return
    engaged = summary["exposure"] > 0
    if benchmark_return > BEARISH_BENCHMARK_RETURN:
        return {
            "applicable": False,
            "engaged": engaged,
            "excess_return": round(excess_return, 6),
            "downside_capture_ratio": None,
            "drawdown_compression_ratio": None,
            "qualified": False,
        }
    downside_capture_ratio = abs(summary["return"]) / abs(benchmark_return)
    benchmark_drawdown = summary["benchmark_drawdown"]
    drawdown_compression_ratio = (
        abs(summary["drawdown"]) / abs(benchmark_drawdown)
        if benchmark_drawdown < 0
        else None
    )
    return {
        "applicable": True,
        "engaged": engaged,
        "excess_return": round(excess_return, 6),
        "downside_capture_ratio": round(downside_capture_ratio, 6),
        "drawdown_compression_ratio": (
            round(drawdown_compression_ratio, 6)
            if drawdown_compression_ratio is not None
            else None
        ),
        "qualified": (
            engaged
            and excess_return > 0
            and downside_capture_ratio <= MAX_DOWNSIDE_CAPTURE_RATIO
            and drawdown_compression_ratio is not None
            and drawdown_compression_ratio <= MAX_DRAWDOWN_COMPRESSION_RATIO
        ),
    }


def _discard_reasons(summary):
    reasons = []
    if summary["completed"] < MIN_COMPLETED_TRADES:
        reasons.append(f"完成交易不足{MIN_COMPLETED_TRADES}笔")
    if (summary["expectancy"] or 0) <= 0:
        reasons.append("成本后单笔期望不为正")
    if (summary["profit_factor"] or 0) < MIN_PROFIT_FACTOR:
        reasons.append(f"利润因子低于{MIN_PROFIT_FACTOR}")
    if summary["return"] <= 0:
        reasons.append("窗口绝对收益不为正")
    if summary["excess_return"] <= 0:
        reasons.append("未跑赢同成本买入持有基准")
    if summary["drawdown"] < MAX_DRAWDOWN:
        reasons.append(f"最大回撤低于{MAX_DRAWDOWN:.0%}门槛")
    if summary["independent_units"] == 1:
        reasons.append("仅有一个独立单位，不能作为跨标的验证")
    elif not summary["cross_unit_pass"]:
        reasons.append("独立单位正收益覆盖不足一半")
    return reasons


def summarize_category(category, universe, evaluations):
    """按独立跟踪单位等权汇总类别，不把同指数 ETF 重复加权。"""
    grouped = defaultdict(dict)
    for code, item in universe.items():
        if item["category"] == category and code in evaluations:
            grouped[item["independent_key"]][code] = evaluations[code]
    units = {
        key: _unit_summary(code_results) for key, code_results in sorted(grouped.items())
    }
    if not units:
        raise ValueError(f"类别{category}没有可评估ETF")
    values = list(units.values())
    profit_factors = [
        item["profit_factor"] for item in values if item["profit_factor"] is not None
    ]
    expectancies = [item["expectancy"] for item in values if item["expectancy"] is not None]
    returns = [item["return"] for item in values]
    summary = {
        "category": category,
        "etf_count": sum(len(item["codes"]) for item in values),
        "independent_units": len(values),
        "evidence_level": "单标的证据" if len(values) == 1 else f"{len(values)}个独立跟踪单位",
        "return": fmean(returns),
        "drawdown": min(item["drawdown"] for item in values),
        "exposure": fmean(item["exposure"] for item in values),
        "completed": sum(item["completed"] for item in values),
        "carry_in_completed": sum(item["carry_in_completed"] for item in values),
        "open": sum(item["open"] for item in values),
        "expectancy": fmean(expectancies) if expectancies else None,
        "profit_factor": fmean(profit_factors) if profit_factors else None,
        "positive_unit_ratio": sum(item["return"] > 0 for item in values) / len(values),
        "benchmark_return": fmean(item["benchmark_return"] for item in values),
        "benchmark_drawdown": min(item["benchmark_drawdown"] for item in values),
        "cross_unit_pass": None
        if len(values) == 1
        else sum(item["return"] > 0 for item in values) / len(values) >= 0.5,
        "units": units,
        "by_etf": {
            code: evaluations[code]
            for code, item in sorted(universe.items())
            if item["category"] == category and code in evaluations
        },
    }
    summary["calmar"] = (
        summary["return"] / -summary["drawdown"] if summary["drawdown"] < 0 else None
    )
    summary["excess_return"] = summary["return"] - summary["benchmark_return"]
    summary["score"] = _category_score(summary)
    summary["discard_reasons"] = _discard_reasons(summary)
    summary["qualified"] = not summary["discard_reasons"]
    return summary


def select_category_leader(category, candidates):
    """只按开发段分数挑选类别领先候选，禁止读取留出表现。"""
    eligible = [
        candidate
        for candidate in candidates
        if category in candidate.get("development", {})
        and candidate.get("research_category", category) == category
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda candidate: (
            candidate["development"][category]["score"],
            candidate["candidate_id"],
        ),
    )


def _factor(factor_id):
    return {"op": "factor", "factor_id": factor_id}


def simplify_expression(expression):
    """消除布尔等价重复，避免同一条件被多次包装成不可审查长公式。"""
    validate_expression(expression)
    return _simplify_expression(expression)


def _simplify_expression(expression):
    operator = expression["op"]
    if operator == "factor":
        return dict(expression)
    if operator == "not":
        child = _simplify_expression(expression["expression"])
        return child["expression"] if child["op"] == "not" else {"op": "not", "expression": child}
    if operator in {"within", "consecutive"}:
        return {
            "op": operator,
            "expression": _simplify_expression(expression["expression"]),
            "days": expression["days"],
        }
    if operator == "after":
        return {
            "op": "after",
            "first": _simplify_expression(expression["first"]),
            "then": _simplify_expression(expression["then"]),
            "days": expression["days"],
        }
    flattened = []
    for item in expression["items"]:
        simplified = _simplify_expression(item)
        flattened.extend(simplified["items"] if simplified["op"] == operator else [simplified])
    deduplicated, seen = [], set()
    for item in flattened:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if marker not in seen:
            seen.add(marker)
            deduplicated.append(item)
    return deduplicated[0] if len(deduplicated) == 1 else {"op": operator, "items": deduplicated}


def expression_is_explainable(expression):
    """以可读中文说明而非因子数限制候选的审查边界。"""
    simplified = simplify_expression(expression)
    return len(_render_expression(simplified)) <= MAX_EXPLANATION_CHARS


def _signature(entry_expression, exit_expression):
    return json.dumps(
        {"entry": entry_expression, "exit": exit_expression},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _seed_expressions():
    return [
        (
            {
                "op": "all",
                "items": [
                    _factor("atr_box_breakout"),
                    _factor("ma60_rising"),
                    _factor("strong_close"),
                ],
            },
            _factor("turning_top"),
            "透明种子：趋势突破",
        ),
        (
            {
                "op": "after",
                "first": {
                    "op": "any",
                    "items": [_factor("atr_oversold"), _factor("wilder_rsi_oversold")],
                },
                "then": _factor("oversold_recovery"),
                "days": 3,
            },
            _factor("turning_top"),
            "透明种子：超跌修复",
        ),
        (
            {
                "op": "all",
                "items": [
                    {"op": "within", "expression": _factor("turning_bottom"), "days": 5},
                    {
                        "op": "within",
                        "expression": _factor("ma5_cross_ma20_up"),
                        "days": 3,
                    },
                    _factor("strong_close"),
                ],
            },
            _factor("turning_top"),
            "透明种子：底部转折",
        ),
    ]


def _factor_paths(expression, path=()):
    operator = expression["op"]
    if operator == "factor":
        return [path]
    if operator in {"all", "any"}:
        return [
            child_path
            for index, item in enumerate(expression["items"])
            for child_path in _factor_paths(item, (*path, "items", index))
        ]
    if operator in {"not", "within", "consecutive"}:
        return _factor_paths(expression["expression"], (*path, "expression"))
    return _factor_paths(expression["first"], (*path, "first")) + _factor_paths(
        expression["then"], (*path, "then"))


def _replace_path(value, path, replacement):
    copied = json.loads(json.dumps(value))
    current = copied
    for key in path[:-1]:
        current = current[key]
    if path:
        current[path[-1]] = replacement
        return copied
    return replacement


def _prune_expression(expression, rng):
    candidates = []
    if expression["op"] in {"all", "any"}:
        candidates.extend(expression["items"])
    if expression["op"] in {"not", "within", "consecutive"}:
        candidates.append(expression["expression"])
    if expression["op"] == "after":
        candidates.extend((expression["first"], expression["then"]))
    return json.loads(json.dumps(rng.choice(candidates))) if candidates else expression


def _mutate_expression(expression, rng):
    """在不改变因子身份的前提下变换组合结构。"""
    factor_id = rng.choice(tuple(FACTORS))
    operation = rng.choice(
        ("all", "any", "not", "within", "consecutive", "after", "replace", "prune")
    )
    copied = json.loads(json.dumps(expression))
    if operation == "all":
        return {"op": "all", "items": [copied, _factor(factor_id)]}
    if operation == "any":
        return {"op": "any", "items": [copied, _factor(factor_id)]}
    if operation == "not":
        return {"op": "not", "expression": copied}
    if operation == "within":
        return {
            "op": "within",
            "expression": copied,
            "days": rng.choice((2, 3, 5, 8)),
        }
    if operation == "consecutive":
        return {
            "op": "consecutive",
            "expression": copied,
            "days": rng.choice((2, 3, 5)),
        }
    if operation == "after":
        return {
            "op": "after",
            "first": _factor(factor_id),
            "then": copied,
            "days": rng.choice((2, 3, 5, 8)),
        }
    if operation == "replace":
        return _replace_path(copied, rng.choice(_factor_paths(copied)), _factor(factor_id))
    return _prune_expression(copied, rng)


def _crossover(first, second, rng):
    return {
        "op": rng.choice(("all", "any")),
        "items": [
            json.loads(json.dumps(first)),
            json.loads(json.dumps(second)),
        ],
    }


def _categories(universe):
    return sorted({item["category"] for item in universe.values()} - {"未分类"})


def holdout_start_date(universe):
    """以最短有效历史的最后20%锁定共同留出段，最少60个交易日。"""
    end = min(item["rows"][-1]["trade_date"] for item in universe.values())
    candidates = [
        item["rows"]
        for item in universe.values()
        if item["rows"][-1]["trade_date"] == end
    ]
    reference = min(candidates, key=len)
    available = len(reference) - RISK_BASELINE["warmup"] - 1
    holdout_days = max(MIN_HOLDOUT_DAYS, round(available * HOLDOUT_RATIO))
    if holdout_days >= available:
        raise ValueError("历史长度不足以划分开发段和留出段")
    return reference[-holdout_days]["trade_date"]


def _new_candidate(
    candidate_id,
    round_number,
    research_category,
    entry,
    exit_expression,
    origin,
    universe,
    stop_date,
):
    evaluations = evaluate_universe(
        universe, entry, exit_expression, stop_date=stop_date
    )
    development = {
        category: summarize_category(category, universe, evaluations)
        for category in _categories(universe)
    }
    return {
        "candidate_id": candidate_id,
        "round": round_number,
        "research_category": research_category,
        "origin": origin,
        "entry_expression": entry,
        "exit_expression": exit_expression,
        "entry_text": render_expression(entry),
        "exit_text": render_expression(exit_expression),
        "development": development,
    }


def _round_candidates(existing, round_number, rng):
    if round_number == 1:
        return _seed_expressions()
    category = existing[0]["research_category"]
    ranked = sorted(
        existing,
        key=lambda candidate: candidate["development"][category]["score"],
        reverse=True,
    )
    parents = ranked[: max(2, min(8, len(ranked)))]
    proposals = []
    for attempt in range(96):
        parent = rng.choice(parents)
        entry, exit_expression = parent["entry_expression"], parent["exit_expression"]
        if attempt % 3 == 0:
            entry = _mutate_expression(entry, rng)
            origin = f"{parent['candidate_id']}：入场结构变异"
        elif attempt % 3 == 1:
            exit_expression = _mutate_expression(exit_expression, rng)
            origin = f"{parent['candidate_id']}：退出结构变异"
        else:
            other = rng.choice(parents)
            entry = _crossover(entry, other["entry_expression"], rng)
            exit_expression = rng.choice(
                (exit_expression, other["exit_expression"])
            )
            origin = f"{parent['candidate_id']}与{other['candidate_id']}：交叉组合"
        proposals.append((entry, exit_expression, origin))
    return proposals


def _fallback_proposals():
    for entry_id in FACTORS:
        for exit_id in FACTORS:
            if entry_id != exit_id:
                yield _factor(entry_id), _factor(exit_id), "透明兜底：单因子入场与单因子退出"


def run_research(universe, rounds=50, *, random_seed=20261127):
    """按类别独立演化可解释因子策略，并在固定留出段后统一报告。"""
    if not isinstance(rounds, int) or rounds < 1:
        raise ValueError("研究轮数必须为正整数")
    if not universe:
        raise ValueError("研究ETF集合不能为空")
    holdout_start = holdout_start_date(universe)
    categories = _categories(universe)
    signatures_by_category = {category: set() for category in categories}
    candidates_by_category = {category: [] for category in categories}
    candidates, round_records = [], []
    for round_number in range(1, rounds + 1):
        category_candidate_ids = {}
        for category_index, category in enumerate(categories):
            rng = random.Random(random_seed + round_number * 100 + category_index)
            proposals = [
                *_round_candidates(candidates_by_category[category], round_number, rng),
                *_fallback_proposals(),
            ]
            candidate_ids = []
            for entry, exit_expression, origin in proposals:
                entry = simplify_expression(entry)
                exit_expression = simplify_expression(exit_expression)
                signature = _signature(entry, exit_expression)
                if (
                    signature in signatures_by_category[category]
                    or not expression_is_explainable(entry)
                    or not expression_is_explainable(exit_expression)
                ):
                    continue
                signatures_by_category[category].add(signature)
                candidate_id = f"c{len(candidates) + 1:04d}"
                candidate = _new_candidate(
                    candidate_id,
                    round_number,
                    category,
                    entry,
                    exit_expression,
                    origin,
                    universe,
                    holdout_start,
                )
                candidates.append(candidate)
                candidates_by_category[category].append(candidate)
                candidate_ids.append(candidate_id)
                if len(candidate_ids) == 3:
                    break
            if len(candidate_ids) != 3:
                raise ValueError(f"类别{category}的可解释候选不足，无法完成本轮研究")
            category_candidate_ids[category] = candidate_ids
        round_records.append(
            {"round": round_number, "category_candidate_ids": category_candidate_ids}
        )

    leaders = {}
    for category in categories:
        leader = select_category_leader(category, candidates_by_category[category])
        if leader is None:
            continue
        holdout = summarize_category(
            category,
            universe,
            evaluate_universe(
                universe,
                leader["entry_expression"],
                leader["exit_expression"],
                start_date=holdout_start,
            ),
        )
        stress = summarize_category(
            category,
            universe,
            evaluate_universe(
                universe,
                leader["entry_expression"],
                leader["exit_expression"],
                start_date=holdout_start,
                costs=STRESS_COSTS,
            ),
        )
        leaders[category] = {
            "candidate_id": leader["candidate_id"],
            "entry_expression": leader["entry_expression"],
            "exit_expression": leader["exit_expression"],
            "entry_text": leader["entry_text"],
            "exit_text": leader["exit_text"],
            "development": leader["development"][category],
            "holdout": holdout,
            "stress": stress,
            "holdout_defense": defense_evidence(holdout),
            "stress_defense": defense_evidence(stress),
            "discard_reasons": sorted(
                set(
                    leader["development"][category]["discard_reasons"]
                    + holdout["discard_reasons"]
                    + stress["discard_reasons"]
                )
            ),
        }
    return {
        "version": RESEARCH_VERSION,
        "rounds": round_records,
        "round_count": rounds,
        "holdout_start": holdout_start,
        "categories": _categories(universe),
        "unclassified_codes": sorted(
            code for code, item in universe.items() if item["category"] == "未分类"
        ),
        "candidates": candidates,
        "category_leaders": leaders,
        "note": "候选仅用于离线研究；留出期不参与候选选择，结果不自动进入生产策略或每日信号。",
    }
