"""固定先验共享择时的全期离线验收，不含候选搜索或生产接入。"""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from copy import deepcopy
from datetime import date
from math import ceil
from statistics import fmean, median

from app.backtest import simulate
from app.shared_etf_research import (
    FIXED_PRIOR_RULES,
    WARMUP,
    prepare_fixed_prior,
    prepare_market,
)
from app.shared_etf_walk_forward import (
    CASH,
    COSTS,
    STRESS,
    drawdown,
    portfolio,
    trade_stats,
)
from app.strategy_research import diagnostics

VERSION = "shared-etf-fixed-prior-v2.0.0"
FIRST_EXECUTION = WARMUP + 1
TRANSFER_CODES = ("518880", "515880", "560780")
ANNUAL_CASH_RATE = 0.015
DAILY_CASH_RATE = (1 + ANNUAL_CASH_RATE) ** (1 / 252) - 1
ORDINARY_PF = 1.25
TAIL_LIMIT = 3.5
UPSIDE_CAPTURE = 0.6
DOWNSIDE_CAPTURE = 0.2
DOWNSIDE_DRAWDOWN = -0.08
SIDEWAYS_EROSION = -0.03

PERTURBATION_AXES = {
    "range_breakout": ("margin", "stop_atr", "trail_atr", "timeout"),
    "left_reversal": ("depth", "stop_atr", "ma_trail_atr", "lookback"),
}


def prepare_universe(universe):
    """准备固定先验所需的因果行情因子，不读取旧研究的外部输入。"""
    return {
        code: {
            "role": item.get("role", "core"),
            "indices": item["indices"],
            "rows": item["rows"],
            "dividends": item["actions"]["dividends"],
            "dates": [row["trade_date"] for row in item["rows"]],
            "market": prepare_market(item["rows"], item["actions"]["dividends"], {}),
        }
        for code, item in universe.items()
    }


def representative_codes(data):
    """用预热期已知覆盖和流动性代理锁定每个指数的一只代表。"""
    groups = defaultdict(list)
    for code, item in data.items():
        if item["role"] != "core" or len(item["rows"]) <= FIRST_EXECUTION:
            continue
        turnover = median(
            float(row["close"]) * float(row["volume"])
            for row in item["rows"][:FIRST_EXECUTION]
        )
        for index in item["indices"]:
            groups[index].append((item["dates"][FIRST_EXECUTION], -turnover, code))
    return [min(groups[index])[2] for index in sorted(groups)]


def common_period(data, reps, cutoff):
    """确定所有固定代表均可预热、且不晚于冻结截止日的连续区间。"""
    start = max(data[code]["dates"][FIRST_EXECUTION] for code in reps)
    stop = min(cutoff, *(data[code]["dates"][-1] for code in reps))
    if start > stop:
        raise ValueError("固定代表没有可共同评估的冻结区间")
    return start, stop


def enrich_rounds(account, rounds, dates):
    """为完整交易附上退出原因、持有交易日和成本后收益率。"""
    enriched = []
    opening = None
    base = {trade["entry_date"] + trade["exit_date"]: trade for trade in rounds}
    for trade in account["trades"]:
        if trade["side"] == "buy":
            opening = trade
        elif opening:
            entry_date, exit_date = opening["trade_date"], trade["trade_date"]
            original = base[entry_date + exit_date]
            denominator = float(opening["notional"]) + float(opening["commission"])
            enriched.append(
                {
                    **original,
                    "exit_reason": trade["reason"],
                    "holding_sessions": dates.index(exit_date)
                    - dates.index(entry_date)
                    + 1,
                    "net_return": float(original["pnl"]) / denominator
                    if denominator
                    else None,
                }
            )
            opening = None
    return enriched


def evaluate(item, start, stop, rule, costs=COSTS, *, benchmark=False):
    """以 65 根预热运行一条全期连续研究账户。"""
    dates = item["dates"]
    begin = max(FIRST_EXECUTION, bisect_left(dates, start))
    end = bisect_right(dates, stop)
    if begin >= end or begin < 1:
        return None
    rows = item["rows"][:end]
    signals = prepare_fixed_prior(
        rows,
        item["dividends"],
        item["market"][:end],
        rule,
        WARMUP,
        slippage_bps=costs["slippage_bps"],
    )
    account = simulate(
        rows,
        item["dividends"],
        {**costs, "end_date": dates[end - 1]},
        signals,
        begin,
        benchmark=benchmark,
    )
    diag = diagnostics(
        account,
        dividend_record_dates={
            event["ex_date"]: event["record_date"] for event in item["dividends"]
        },
    )
    rounds = enrich_rounds(account, diag["rounds"], dates)
    return {
        "pnl": [float(round_["pnl"]) for round_ in rounds],
        "rounds": rounds,
        "daily": account["daily"],
        "open": diag["open_rounds"],
        "return": account["metrics"]["total_return"],
        "drawdown": account["metrics"]["max_drawdown"],
        "exposure": diag["time_in_market"],
        "fills": account["trades"],
        "dividends": account["dividends"],
    }


def calmar(stats):
    """回撤为零时不虚构无限卡玛。"""
    return stats["return"] / -stats["drawdown"] if stats["drawdown"] < 0 else None


def with_cash_reference(stats, accounts):
    """按每日收盘闲置现金简单计息，只作辅助参考而不改变成交账户。"""
    interest = sum(
        float(row["cash"]) * DAILY_CASH_RATE
        for account in accounts.values()
        if account is not None
        for row in account["daily"]
    )
    funded = CASH * sum(account is not None for account in accounts.values())
    return {
        "annual_rate": ANNUAL_CASH_RATE,
        "cash_interest": interest,
        "return_increment": interest / funded if funded else None,
        "reference_return": stats["return"] + interest / funded if funded else None,
    }


def summarize(accounts):
    """汇总等资金账户，并补充卡玛与闲置现金参考。"""
    stats, pnl, curve = portfolio(accounts, per_etf=True)
    return (
        {
            **stats,
            "calmar": calmar(stats),
            "cash_reference": with_cash_reference(stats, accounts),
            "nav": curve,
        },
        pnl,
        curve,
    )


def quarter_key(day):
    value = date.fromisoformat(day)
    return f"{value.year}-Q{(value.month - 1) // 3 + 1}"


def regime_scorecard(strategy, benchmark):
    """按季度等权基准收益分类，计算预注册的非对称市况指标。"""
    strategy_by_day = dict(strategy)
    benchmark_by_quarter = defaultdict(list)
    for day, nav in benchmark:
        benchmark_by_quarter[quarter_key(day)].append((day, nav))
    prior_strategy = prior_benchmark = 1.0
    buckets = defaultdict(list)
    for quarter in sorted(benchmark_by_quarter):
        benchmark_points = benchmark_by_quarter[quarter]
        strategy_points = [
            (day, strategy_by_day[day])
            for day, _ in benchmark_points
            if day in strategy_by_day
        ]
        if not strategy_points:
            continue
        benchmark_return = benchmark_points[-1][1] / prior_benchmark - 1
        strategy_return = strategy_points[-1][1] / prior_strategy - 1
        normalized = [(day, nav / prior_strategy) for day, nav in strategy_points]
        state = (
            "上涨"
            if benchmark_return > 0.05
            else "下跌"
            if benchmark_return < -0.05
            else "震荡"
        )
        buckets[state].append(
            {
                "quarter": quarter,
                "benchmark_return": benchmark_return,
                "strategy_return": strategy_return,
                "max_drawdown": drawdown(normalized),
                "days": (
                    date.fromisoformat(strategy_points[-1][0])
                    - date.fromisoformat(strategy_points[0][0])
                ).days
                + 1,
            }
        )
        prior_strategy = strategy_points[-1][1]
        prior_benchmark = benchmark_points[-1][1]
    result = {}
    for state in ("上涨", "震荡", "下跌"):
        values = buckets[state]
        result[state] = {"quarters": values, "count": len(values)}
        if state == "上涨":
            denominator = sum(row["benchmark_return"] for row in values)
            result[state]["upside_capture"] = (
                sum(row["strategy_return"] for row in values) / denominator
                if denominator
                else None
            )
        elif state == "下跌":
            denominator = sum(-row["benchmark_return"] for row in values)
            result[state]["downside_capture"] = (
                sum(max(0, -row["strategy_return"]) for row in values) / denominator
                if denominator
                else None
            )
            result[state]["max_drawdown"] = min(
                (row["max_drawdown"] for row in values), default=None
            )
        else:
            total_days = sum(row["days"] for row in values)
            compounded = 1.0
            for row in values:
                compounded *= 1 + row["strategy_return"]
            result[state]["annualized_erosion"] = (
                compounded ** (365 / total_days) - 1 if total_days else None
            )
    return result


def parameter_perturbations(rule):
    """预注册中心规则的单轴 ±20% 邻点；不输出排序或推荐值。"""
    points = []
    for axis in PERTURBATION_AXES[rule["family"]]:
        for multiplier, direction in ((0.8, "-20%"), (1.2, "+20%")):
            changed = deepcopy(rule)
            value = rule[axis] * multiplier
            changed[axis] = (
                max(1, round(value)) if isinstance(rule[axis], int) else value
            )
            points.append({"axis": axis, "direction": direction, "rule": changed})
    return points


def combine_nav_curves(curves):
    """生成多条独立等资金净值的事后等权合成曲线。"""
    if not curves:
        return []
    common = {day for day, _ in curves[0]}
    for curve in curves[1:]:
        common.intersection_update(day for day, _ in curve)
    lookups = [dict(curve) for curve in curves]
    return [(day, fmean(lookup[day] for lookup in lookups)) for day in sorted(common)]


def transfer_coverage(universe):
    """只报告冻结输入是否覆盖迁移标的，禁止在研究时补采。"""
    result = {}
    for code in TRANSFER_CODES:
        item = universe.get(code)
        if item is None:
            result[code] = {"status": "未验证", "reason": "冻结输入未包含标的"}
        elif len(item["rows"]) <= FIRST_EXECUTION:
            result[code] = {
                "status": "未验证",
                "reason": "有效行情不足65根预热及首日执行",
            }
        else:
            result[code] = {"status": "可评估"}
    return result


def acceptance_checks(stats, stress, scorecard, benchmark):
    """固定先验的预注册通过条件，不对历史观察数据自动发布。"""
    downside = scorecard["下跌"]
    upside = scorecard["上涨"]
    sideways = scorecard["震荡"]
    checks = {
        "positive_return": stats["return"] > 0,
        "profit_factor": (stats["profit_factor"] or 0) >= ORDINARY_PF,
        "tail": stats["tail_ratio"] is not None and stats["tail_ratio"] <= TAIL_LIMIT,
        "calmar_outperforms_buy_and_hold": stats["calmar"] is not None
        and benchmark["calmar"] is not None
        and stats["calmar"] > benchmark["calmar"],
        "stress_expectancy": (stress["expectancy"] or 0) > 0,
        "upside_capture": upside["upside_capture"] is not None
        and upside["upside_capture"] >= UPSIDE_CAPTURE,
        "downside_capture": downside["downside_capture"] is not None
        and downside["downside_capture"] <= DOWNSIDE_CAPTURE,
        "downside_drawdown": downside["max_drawdown"] is not None
        and downside["max_drawdown"] >= DOWNSIDE_DRAWDOWN,
        "sideways_erosion": sideways["annualized_erosion"] is not None
        and sideways["annualized_erosion"] >= SIDEWAYS_EROSION,
    }
    return {**checks, "all": all(checks.values())}


def left_reversal_attribution(accounts):
    """归因只描述已有交易结构，不反向更改固定参数。"""
    rounds = [round_ for account in accounts.values() for round_ in account["rounds"]]
    wins = [float(round_["pnl"]) for round_ in rounds if float(round_["pnl"]) > 0]
    losses = [-float(round_["pnl"]) for round_ in rounds if float(round_["pnl"]) < 0]
    ma20 = [
        round_["net_return"]
        for round_ in rounds
        if "MA20" in round_["exit_reason"] and round_["net_return"] is not None
    ]
    early_stop = [
        round_
        for round_ in rounds
        if round_["holding_sessions"] <= 3 and "ATR初始止损" in round_["exit_reason"]
    ]
    return {
        "completed": len(rounds),
        "average_win": fmean(wins) if wins else None,
        "average_loss": fmean(losses) if losses else None,
        "ma20_exit_average_return": fmean(ma20) if ma20 else None,
        "initial_stop_within_3_sessions_ratio": len(early_stop) / len(rounds)
        if rounds
        else None,
    }


def run_accounts(data, reps, start, stop, rule, costs=COSTS, *, benchmark=False):
    return {
        code: evaluate(data[code], start, stop, rule, costs, benchmark=benchmark)
        for code in reps
    }


def run_fixed_prior(universe, cutoff):
    """运行固定先验中心、压力、扰动与迁移检查，不执行选参。"""
    data = prepare_universe(universe)
    reps = representative_codes(data)
    if not reps:
        raise ValueError("冻结输入没有可完成65根预热的指数代表")
    start, stop = common_period(data, reps, cutoff)
    benchmark_accounts = run_accounts(
        data, reps, start, stop, FIXED_PRIOR_RULES["range_breakout"], benchmark=True
    )
    benchmark, _, benchmark_curve = summarize(benchmark_accounts)
    summaries = {"buy_and_hold": benchmark}
    raw_accounts = {}
    plateaus = {}
    for label, rule in FIXED_PRIOR_RULES.items():
        accounts = run_accounts(data, reps, start, stop, rule)
        stats, _, curve = summarize(accounts)
        stressed, _, _ = summarize(run_accounts(data, reps, start, stop, rule, STRESS))
        scorecard = regime_scorecard(curve, benchmark_curve)
        summaries[label] = {
            **stats,
            "scorecard": scorecard,
            "stress": stressed,
            "checks": acceptance_checks(stats, stressed, scorecard, benchmark),
        }
        raw_accounts[label] = accounts
        points = []
        for point in parameter_perturbations(rule):
            perturbed, _, perturbed_curve = summarize(
                run_accounts(data, reps, start, stop, point["rule"])
            )
            score = regime_scorecard(perturbed_curve, benchmark_curve)
            passes = {
                "positive_return": perturbed["return"] > 0,
                "downside_drawdown": score["下跌"]["max_drawdown"] is not None
                and score["下跌"]["max_drawdown"] >= DOWNSIDE_DRAWDOWN,
                "outperforms_buy_and_hold": perturbed["return"] > benchmark["return"],
            }
            points.append(
                {
                    **point,
                    "summary": {
                        key: perturbed[key]
                        for key in (
                            "completed",
                            "expectancy",
                            "profit_factor",
                            "return",
                            "drawdown",
                        )
                    },
                    "downside_max_drawdown": score["下跌"]["max_drawdown"],
                    "checks": {**passes, "all": all(passes.values())},
                }
            )
        passed = sum(point["checks"]["all"] for point in points)
        plateaus[label] = {
            "points": points,
            "passed_points": passed,
            "required_points": ceil(len(points) * 0.8),
            "fraction": passed / len(points) if points else None,
            "passes": passed >= ceil(len(points) * 0.8),
        }
        summaries[label]["checks"]["parameter_plateau"] = plateaus[label]["passes"]
        summaries[label]["checks"]["all"] = all(summaries[label]["checks"].values())
    combo_curve = combine_nav_curves(
        [summaries[label]["nav"] for label in FIXED_PRIOR_RULES]
    )
    combo_pnl = [
        0.5 * pnl
        for label in FIXED_PRIOR_RULES
        for account in raw_accounts[label].values()
        for pnl in account["pnl"]
    ]
    combined = {
        **trade_stats(combo_pnl),
        "return": combo_curve[-1][1] - 1 if combo_curve else 0.0,
        "drawdown": drawdown(combo_curve),
        "calmar": None,
        "nav": combo_curve,
    }
    combined["calmar"] = calmar(combined)
    coverage = transfer_coverage(universe)
    for code, status in coverage.items():
        if status["status"] != "可评估":
            continue
        item = data[code]
        transfer_start = item["dates"][FIRST_EXECUTION]
        transfer_stop = min(cutoff, item["dates"][-1])
        baseline = evaluate(
            item,
            transfer_start,
            transfer_stop,
            FIXED_PRIOR_RULES["range_breakout"],
            benchmark=True,
        )
        baseline_stats, _, baseline_curve = summarize({code: baseline})
        tracks = {}
        for label, rule in FIXED_PRIOR_RULES.items():
            account = evaluate(item, transfer_start, transfer_stop, rule)
            stats, _, curve = summarize({code: account})
            tracks[label] = {
                **stats,
                "scorecard": regime_scorecard(curve, baseline_curve),
                "drawdown_reduction": (
                    1 - abs(stats["drawdown"]) / abs(baseline_stats["drawdown"])
                    if baseline_stats["drawdown"] < 0
                    else None
                ),
            }
        coverage[code] = {
            "status": "已评估",
            "start": transfer_start,
            "stop": transfer_stop,
            "buy_and_hold": baseline_stats,
            "tracks": tracks,
        }
    return {
        "version": VERSION,
        "representatives": reps,
        "period": {"start": start, "stop": stop, "warmup_bars": WARMUP + 1},
        "fixed_rules": FIXED_PRIOR_RULES,
        "ordinary_costs": COSTS,
        "stress_costs": STRESS,
        "summaries": summaries,
        "left_reversal_attribution": left_reversal_attribution(
            raw_accounts["left_reversal"]
        ),
        "parameter_plateaus": plateaus,
        "equal_weight_combination": combined,
        "transfer": coverage,
        "eligible_for_release": False,
    }
