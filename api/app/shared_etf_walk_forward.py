"""按指数去重、逐季度锁定参数并评估的离线研究流程。"""

from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta
from itertools import product
from statistics import fmean, median

from app.algorithm_templates import (
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    template_snapshot,
    turning_events,
)
from app.backtest import simulate
from app.multifactor_research import build_factors, prepare_signals
from app.shared_etf_research import RULES, prepare_market, prepare_shared
from app.strategies import Decision
from app.strategy_research import diagnostics

CASH = 50_000
COSTS = {
    "initial_cash": CASH,
    "commission_rate": 0.0001,
    "minimum_commission": 0,
    "slippage_bps": 5,
}
STRESS = {
    **COSTS,
    "commission_rate": 0.0003,
    "minimum_commission": 5,
    "slippage_bps": 10,
}
MIN_TRADES = 60
TRAIN_MIN_TRADES = 12
TRAIN_MIN_INDICES = 4
MIN_PF = 1.3
MAX_TAIL = 5.0  # 单笔最大净亏损／平均净盈利，只作研究准入。
DRAWDOWN_LIMIT = -0.15
FIRST_EXECUTION = 120  # 对照组最长 MA120，所有方案使用相同起点。
AXES = {
    "range_breakout": {
        "margin": (0.1, 0.2, 0.3),
        "stop_atr": (1.5, 2.0, 2.5),
        "trail_atr": (2.0, 2.5, 3.0),
        "timeout": (14, 18, 22),
    },
    "bottom_reversal": {"depth": (1.0, 1.5, 2.0), "stop_atr": (1.5, 2.0, 2.5)},
}
BASELINES = ("legacy_multifactor", "legacy_breakout", "buy_and_hold")
ABLATION = "range_breakout_two_of_three"


def folds(first, last):
    """左闭右开；最后一折可不完整。"""
    start = date.fromisoformat(first)
    end = date.fromisoformat(last) + timedelta(days=1)
    if start.day != 1 or start.month not in (1, 4, 7, 10) or start >= end:
        raise ValueError("首个验证日须为范围内的季度首日")
    while start < end:
        next_start = date(
            start.year + int(start.month == 10), (start.month + 2) % 12 + 1, 1
        )
        yield (
            str(start.replace(year=start.year - 1)),
            str(start),
            str(min(end, next_start)),
        )
        start = next_start


def validate_split_cutoffs(universe, first):
    """冻结快照在最后一次折算后起算，不允许将留出起点回拨至折算之前。"""
    excluded = {
        code: item["excluded_splits"]
        for code, item in universe.items()
        if item["excluded_splits"]
    }
    if any(day >= first for dates in excluded.values() for day in dates):
        raise ValueError("首个留出日须晚于冻结快照已裁剪的全部份额折算日")
    return excluded


def representative_codes(universe, first_execution, start, stop):
    """按已预热的训练覆盖、成交额代理、代码排序，不读取留出期成交量。"""
    groups = defaultdict(list)
    for code, item in universe.items():
        sample = [
            r
            for r in item["rows"][first_execution[code] :]
            if start <= r["trade_date"] < stop
        ]
        if sample:
            liquidity = median(float(r["volume"]) * float(r["close"]) for r in sample)
            groups[item["index"]].append((len(sample), liquidity, code))
    return [max(groups[index])[-1] for index in sorted(groups)]


def candidates(family):
    axes = AXES[family]
    return [
        {**RULES[family], **dict(zip(axes, combination, strict=True))}
        for combination in product(*axes.values())
    ]


def neighbors(rule, grid, family):
    return [
        item
        for item in grid
        if sum(
            abs(values.index(rule[key]) - values.index(item[key]))
            for key, values in AXES[family].items()
        )
        == 1
    ]


def trade_stats(pnl):
    """只统计完整交易的成本后净盈亏；无亏损样本的 PF 不作无穷大。"""
    wins = [value for value in pnl if value > 0]
    losses = [-value for value in pnl if value < 0]
    mean_win = fmean(wins) if wins else None
    worst = max(losses, default=0.0)
    return {
        "completed": len(pnl),
        "wins": len(wins),
        "win_rate": len(wins) / len(pnl) if pnl else None,
        "expectancy": fmean(pnl) if pnl else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "payoff": mean_win / fmean(losses) if wins and losses else None,
        "worst_loss": worst,
        "tail_ratio": worst / mean_win if wins else None,
    }


def prepare_universe(universe):
    """特征可预先计算：两代因子均只依赖当日及历史，决策每折另算。"""
    result = {}
    for code, item in universe.items():
        rows, dividends = item["rows"], item["actions"]["dividends"]
        legacy = template_snapshot(TEMPLATE_ID, TEMPLATE_VERSION, code)
        old_breakout = template_snapshot("range_breakout", "1.0.0", code)
        events = turning_events(rows, dividends, legacy["turning"]["parameters"])
        result[code] = {
            "index": item["indices"][0],
            "rows": rows,
            "dividends": dividends,
            "dates": [row["trade_date"] for row in rows],
            "market": prepare_market(rows, dividends, events),
            "old_factors": build_factors(
                rows,
                dividends,
                events,
                item["external"],
            ),
            "legacy_multifactor": legacy["rule"],
            "legacy_breakout": old_breakout["rule"],
        }
    return result


def evaluate(item, start, stop, rule, costs=COSTS, *, details=False, schedule=None):
    dates = item["dates"]
    begin = max(FIRST_EXECUTION, bisect_left(dates, start))
    end = bisect_left(dates, stop)
    if begin >= end:
        return None
    rows, dividends = item["rows"][begin - FIRST_EXECUTION : end], item["dividends"]
    offset = begin - FIRST_EXECUTION
    # 因子使用完整因果前缀，账户在首个有效交易日开始计值。
    if isinstance(rule, str):
        signals = prepare_signals(
            rows,
            dividends,
            item["old_factors"][offset:end],
            item["legacy_breakout" if rule == "buy_and_hold" else rule],
            FIRST_EXECUTION - 1,
            slippage_bps=costs["slippage_bps"],
        )
    else:
        entry_updates = {
            max(begin, decision_day): template
            for day, template in sorted((schedule or {}).items())
            if (decision_day := bisect_left(dates, day)) < end
        }
        signals = prepare_shared(
            item["rows"][:end],
            dividends,
            item["market"][:end],
            rule,
            begin if schedule is not None else begin - 1,
            slippage_bps=costs["slippage_bps"],
            entry_updates=entry_updates,
        )[offset:]
        if schedule is not None:
            # 季度参数从当季首个收盘生效，不重写前一收盘；首折没有继承目标。
            signals[FIRST_EXECUTION - 1]["decision"] = Decision(0, "等待首个验证收盘")
    account = simulate(
        rows,
        dividends,
        {**costs, "end_date": dates[end - 1]},
        signals,
        FIRST_EXECUTION,
        benchmark=rule == "buy_and_hold",
    )
    diag = diagnostics(
        account,
        dividend_record_dates={
            event["ex_date"]: event["record_date"] for event in dividends
        },
    )
    pnl = [float(trade["pnl"]) for trade in diag["rounds"]]
    result = {
        "pnl": pnl,
        "rounds": diag["rounds"],
        "daily": account["daily"],
        "open": diag["open_rounds"],
        "return": account["metrics"]["total_return"],
        "drawdown": account["metrics"]["max_drawdown"],
        "exposure": diag["time_in_market"],
    }
    if details:
        result["dividends"] = account["dividends"]
        result["fills"] = [
            {
                **fill,
                "signal_evidence": signals[
                    bisect_left(dates, fill["signal_date"]) - offset
                ]["indicators"],
            }
            if fill["signal_date"] is not None
            else fill
            for fill in account["trades"]
        ]
    return result


def etf_summary(item):
    return (
        None
        if item is None
        else {
            **trade_stats(item["pnl"]),
            **{
                key: item[key]
                for key in (
                    "return",
                    "drawdown",
                    "open",
                    "exposure",
                    "fills",
                    "rounds",
                    "dividends",
                )
            },
        }
    )


def portfolio(results, *, per_etf=False):
    changes = defaultdict(float)
    pnl = []
    funded = CASH * len(results)
    positions = observations = opened = 0
    for result in results.values():
        if result is None:
            continue
        previous = CASH
        for row in result["daily"]:
            current = float(row["equity"])
            changes[row["trade_date"]] += current - previous
            previous = current
            observations += 1
            positions += row["quantity"] > 0
        pnl.extend(result["pnl"])
        opened += result["open"]
    nav = 1.0
    curve = []
    for day, change in sorted(changes.items()):
        nav += change / funded
        curve.append((day, nav))
    summary = {
        **trade_stats(pnl),
        "return": nav - 1,
        "drawdown": drawdown(curve),
        "open": opened,
        "exposure": positions / observations if observations else None,
    }
    if per_etf:
        summary["by_etf"] = {code: etf_summary(item) for code, item in results.items()}
    return summary, pnl, curve


def drawdown(curve):
    peak, worst = 1.0, 0.0
    for _, nav in curve:
        peak = max(peak, nav)
        worst = min(worst, nav / peak - 1)
    return worst


def economic_checks(stats, *, min_trades=MIN_TRADES):
    return {
        "trades": stats["completed"] >= min_trades,
        "positive_expectancy": (stats["expectancy"] or 0) > 0,
        "profit_factor": (stats["profit_factor"] or 0) >= MIN_PF,
        "positive_return": stats["return"] > 0,
        "drawdown": stats["drawdown"] >= DRAWDOWN_LIMIT,
        "tail": stats["tail_ratio"] is not None and stats["tail_ratio"] <= MAX_TAIL,
    }


def select_rule(family, stats):
    """先通过经济门槛，再按收益回撤排序；相邻参数不可大幅塌方。"""
    grid = candidates(family)
    ranked = []
    for i, (rule, result) in enumerate(zip(grid, stats, strict=True)):
        adjacent = [stats[grid.index(peer)] for peer in neighbors(rule, grid, family)]
        stable = all(
            (p["expectancy"] or 0) > 0
            and (p["profit_factor"] or 0) >= 1
            and p["return"] >= result["return"] / 2
            and p["completed"] >= TRAIN_MIN_TRADES // 2
            for p in adjacent
        )
        if (
            stable
            and result["contributing_indices"] >= TRAIN_MIN_INDICES
            and all(economic_checks(result, min_trades=TRAIN_MIN_TRADES).values())
        ):
            # 短窗口不盲目年化；回撤分母下限避免接近零时排名失真。
            ranked.append((result["return"] / max(0.01, -result["drawdown"]), i))
    return grid[max(ranked)[1]] if ranked else None


def fold_summary(accounts, curve, start, stop):
    """截取连续账本计值；完整交易按自然卖出日期归折，不做季末结算。"""
    before = next((nav for day, nav in reversed(curve) if day < start), 1.0)
    period = [(day, nav / before) for day, nav in curve if start <= day < stop]
    rounds = []
    carried_in = carried_out = 0
    for item in accounts.values():
        if item is None:
            continue
        rounds.extend(
            trade for trade in item["rounds"] if start <= trade["exit_date"] < stop
        )
        carried_in += next(
            (
                r["quantity"] > 0
                for r in reversed(item["daily"])
                if r["trade_date"] < start
            ),
            False,
        )
        carried_out += next(
            (
                r["quantity"] > 0
                for r in reversed(item["daily"])
                if r["trade_date"] < stop
            ),
            False,
        )
    return {
        **trade_stats([float(trade["pnl"]) for trade in rounds]),
        "return": (period[-1][1] - 1) if period else 0.0,
        "drawdown": drawdown(period),
        "carried_in": carried_in,
        "carried_out": carried_out,
        "cross_fold_closed": sum(trade["entry_date"] < start for trade in rounds),
    }


def training_stats(data, reps, start, stop, rule):
    accounts = {code: evaluate(data[code], start, stop, rule) for code in reps}
    return {
        **portfolio(accounts)[0],
        "contributing_indices": sum(
            bool(account and account["rounds"]) for account in accounts.values()
        ),
    }


def walk_forward(universe, first, last):
    data = prepare_universe(universe)
    periods = list(folds(first, last))
    # 固定首折代表，避免换代表时并持同指数或暗中平仓。选择不引用留出期。
    reps = representative_codes(
        data, dict.fromkeys(data, FIRST_EXECUTION), periods[0][0], first
    )
    if not reps:
        raise ValueError("首折没有可预热的训练期代表，请调整验证起点")
    fold_reports = []
    schedules = {key: {} for key in (*RULES, ABLATION)}
    for train_start, start, stop in periods:
        selected, training = {}, {}
        for family in RULES:
            grid = candidates(family)
            stats = [
                training_stats(data, reps, train_start, start, rule) for rule in grid
            ]
            selected[family] = select_rule(family, stats)
            schedules[family][start] = selected[family] or RULES[family]
            training[family] = [
                {"rule": rule, "stats": summary}
                for rule, summary in zip(grid, stats, strict=True)
            ]
        schedules[ABLATION][start] = {
            **schedules["range_breakout"][start],
            "confirmations_required": 2,
        }
        coverage = {}
        for code in reps:
            dates = data[code]["dates"]
            left = max(FIRST_EXECUTION, bisect_left(dates, train_start))
            right = bisect_left(dates, start)
            coverage[code] = (
                {"first": dates[left], "last": dates[right - 1]}
                if left < right
                else None
            )
        fold_reports.append(
            {
                "train_start": train_start,
                "start": start,
                "stop": stop,
                "training_coverage": coverage,
                "selected": selected,
                "training": training,
                "evaluated_rules": {
                    label: schedule[start] for label, schedule in schedules.items()
                },
                "validation": {},
                "stress": {},
            }
        )

    summaries = {}
    final_stop = periods[-1][2]
    for label in (*BASELINES, *schedules):
        schedule = schedules.get(label)
        rule = schedule[first] if schedule is not None else label
        results = {
            code: evaluate(
                item, first, final_stop, rule, details=True, schedule=schedule
            )
            for code, item in data.items()
        }
        accounts = {code: results[code] for code in reps}
        summary, _, curve = portfolio(accounts, per_etf=True)
        summaries[label] = {
            **summary,
            "nav": curve,
            "transfer": {
                code: etf_summary(item)
                for code, item in results.items()
                if code not in reps
            },
        }
        for fold in fold_reports:
            fold["validation"][label] = fold_summary(
                accounts, curve, fold["start"], fold["stop"]
            )
        if schedule is not None:
            stressed = {
                code: evaluate(
                    data[code], first, final_stop, rule, STRESS, schedule=schedule
                )
                for code in reps
            }
            stress_summary, _, stress_curve = portfolio(stressed)
            summaries[f"{label}_stress"] = {**stress_summary, "nav": stress_curve}
            for fold in fold_reports:
                fold["stress"][label] = fold_summary(
                    stressed, stress_curve, fold["start"], fold["stop"]
                )

    for fold in fold_reports:
        benchmark = fold["validation"]["buy_and_hold"]["return"]
        fold["regime"] = (
            "上涨" if benchmark >= 0.05 else "下跌" if benchmark <= -0.05 else "震荡"
        )
    for label in schedules:
        regime_counts = defaultdict(int)
        for fold in fold_reports:
            regime_counts[fold["regime"]] += fold["validation"][label]["completed"]
        stress = summaries[f"{label}_stress"]
        summaries[label]["trades_by_exit_regime"] = dict(regime_counts)
        summaries[label]["cross_fold_closed"] = sum(
            f["validation"][label]["cross_fold_closed"] for f in fold_reports
        )
        family = "range_breakout" if label == ABLATION else label
        summaries[label]["checks"] = {
            **economic_checks(summaries[label]),
            "regime_coverage": sum(count > 0 for count in regime_counts.values()) >= 2,
            "training_selection": all(
                f["selected"][family] is not None for f in fold_reports
            ),
            "cost_stress_sample": stress["completed"] >= MIN_TRADES,
            "cost_stress_direction": (stress["expectancy"] or 0) > 0
            and (stress["profit_factor"] or 0) >= 1
            and stress["return"] > 0,
        }
    return {"representatives": reps, "folds": fold_reports, "summaries": summaries}
