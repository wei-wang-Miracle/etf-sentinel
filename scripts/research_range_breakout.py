"""用冻结行情进行最多30轮共享箱体策略试验并记录留出验证。"""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import fmean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.algorithm_templates import (
    SHARED_WARMUP_BARS,
    template_snapshot,
    turning_events,
    turning_profile,
)
from app.backtest import ENGINE_VERSION, simulate
from app.multifactor_research import build_factors, prepare_signals
from app.strategy_research import diagnostics

BASELINE = {"rule": template_snapshot("range_breakout", "1.0.0", "510500")["rule"]}
COSTS = {
    "initial_cash": 50000,
    "commission_rate": 0.0001,
    "minimum_commission": 0,
    "slippage_bps": 5,
}
TRAIN_END = "2026-03-31"
HOLDOUT_START = "2026-04-01"
HOLDOUT_END = "2026-11-16"
TRAIN_MIN, HOLDOUT_MIN = 8, 5
MAX_ROUNDS = 30


def prepare_market(item, instrument_code="510500"):
    """在含息价格尺度计算因果波幅、形态和 Wilder RSI。"""
    rows = item["rows"]
    dividends = item["actions"]["dividends"]
    factors = build_factors(
        rows,
        dividends,
        turning_events(rows, dividends, turning_profile(instrument_code)["parameters"]),
    )
    values = [f["signal_index"] for f in factors]
    true_ranges, context, moving = [], [], []
    gain = loss = 0.0
    for i, (row, value) in enumerate(zip(rows, values, strict=True)):
        close = float(row["close"])
        scale = value / close
        high, low = float(row["high"]) * scale, float(row["low"]) * scale
        previous = values[i - 1] if i else value
        true_ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        atr = fmean(true_ranges[i - 19 : i + 1]) if i >= 19 else 0
        moving.append(fmean(values[i - 59 : i + 1]) if i >= 59 else None)
        if i:
            up, down = max(value - previous, 0), max(previous - value, 0)
            if i <= 14:
                gain, loss = gain + up / 14, loss + down / 14
            else:
                gain, loss = (gain * 13 + up) / 14, (loss * 13 + down) / 14
        prior = values[i - 20 : i] if i >= 20 else []
        context.append(
            {
                "atr": atr,
                "raw_atr": atr / scale,
                "margin": value - max(prior) if prior else 0,
                "position": (value - low) / (high - low) if high > low else 0,
                "gain": value - previous,
                "rising": i >= 64 and moving[i] >= moving[i - 5],
                "width": max(prior) / min(prior) - 1 if prior else None,
                "wilder": (100 * gain / (gain + loss) if gain + loss else 50)
                if i >= 14
                else None,
            }
        )
    return {
        "rows": rows,
        "dividends": dividends,
        "factors": factors,
        "context": context,
    }


def filter_entries(data, trial):
    """将箱体专用门槛加在必投的突破结构票上。"""
    rule = trial["rule"]
    filters = trial.get("filters", {})
    if not filters and "atr_stop" not in trial:
        return data["factors"]
    window = rule["break_window"]
    result = []
    for i, (f, bar) in enumerate(zip(data["factors"], data["context"], strict=True)):
        passes = f["break_up"][window]
        if i >= SHARED_WARMUP_BARS - 1 and passes:
            # 保留不同突破窗口下的同一波幅单位。
            margin = (
                bar["margin"]
                if window == 20
                else f["signal_index"]
                - max(prev["signal_index"] for prev in data["factors"][i - window : i])
            )
            passes = (
                ("margin" not in filters or margin > filters["margin"] * bar["atr"])
                and (
                    "position" not in filters or bar["position"] >= filters["position"]
                )
                and (
                    "impulse" not in filters
                    or bar["gain"] <= filters["impulse"] * bar["atr"]
                )
                and ("bias_max" not in filters or f["bias"][60] <= filters["bias_max"])
                and (not filters.get("rising") or bar["rising"])
                and (
                    "volume_max" not in filters
                    or f["volume_ratio"] <= filters["volume_max"]
                )
                and ("width" not in filters or bar["width"] <= filters["width"])
                and ("atr_stop" not in trial or bar["raw_atr"] > 0)
            )
        result.append({**f, "break_up": {**f["break_up"], window: passes}})
    return result


def atr_exit_policy(context, trial):
    """以信号日 ATR 锚定风险，移动保护只上调，并按收盘产生目标。"""
    protection = None

    def exits(i, entry_index, entry_price, holding_return, peak, f):
        nonlocal protection
        atr_at_signal = context[entry_index - 1]["raw_atr"] / float(entry_price)
        if i == entry_index:
            protection = None
        reasons = []
        if holding_return <= -min(0.07, trial["atr_stop"] * atr_at_signal):
            reasons.append("ATR初始止损")
        if (
            "atr_profit" in trial
            and holding_return >= trial["atr_profit"] * atr_at_signal
        ):
            reasons.append("ATR止盈")
        if peak >= 2.5 * atr_at_signal:
            multiplier = (
                trial["atr_trail"]
                if peak < 5 * atr_at_signal
                else min(1.8, trial["atr_trail"])
            )
            if trial.get("layered") and (
                f["top_age"] <= 5
                or (context[i]["wilder"] >= 75 and f["momentum"][1] < 0)
            ):
                multiplier = min(1.2, multiplier)
            protection = max(
                protection or 0,
                peak - multiplier * context[i]["raw_atr"] / float(entry_price),
            )
            if holding_return <= protection:
                reasons.append("ATR移动退出")
        if i - entry_index + 1 >= trial["atr_days"] and holding_return < atr_at_signal:
            reasons.append("弱势时间止损")
        if trial.get("layered"):
            if f["bias"][20] < 0 and f["momentum"][3] < 0:
                reasons.append("20日趋势破位")
        else:
            score = sum(
                (
                    f["top_age"] <= 5,
                    f["bias"][10] < 0 and f["momentum"][3] < 0,
                    f["rsi"][14] >= 70 and f["momentum"][1] < 0,
                )
            )
            if score >= 2:
                reasons.append(f"风险汇总{score}票")
        return reasons

    return exits


def evaluate(data, trial, start, end, *, benchmark=False):
    """在指定窗口独立开账，按真实模拟成交统计净盈亏。"""
    rows, dividends = data["rows"], data["dividends"]
    begin = next(
        (
            i
            for i, row in enumerate(rows)
            if i >= SHARED_WARMUP_BARS and start <= row["trade_date"] <= end
        ),
        None,
    )
    if begin is None:
        return None
    settings = {**COSTS, "start_date": rows[begin]["trade_date"], "end_date": end}
    signals = prepare_signals(
        rows,
        dividends,
        filter_entries(data, trial),
        trial["rule"],
        begin - 1,
        exit_policy=atr_exit_policy(data["context"], trial)
        if "atr_stop" in trial
        else None,
    )
    account = simulate(rows, dividends, settings, signals, begin, benchmark=benchmark)
    diag = diagnostics(account)
    pnl = [float(r["pnl"]) for r in diag["rounds"]]
    wins = sum(value > 0 for value in pnl)
    trades = account["trades"]
    signals_by_day = {
        row["trade_date"]: signal for row, signal in zip(rows, signals, strict=True)
    }
    for r, buy, sell in zip(diag["rounds"], trades[::2], trades[1::2]):
        checks = signals_by_day[buy["signal_date"]]["indicators"]["buy"]
        r.update(
            entry_signal=buy["signal_date"],
            exit_signal=sell["signal_date"],
            exits=sell["reason"].split("：", 1)[-1].split("、"),
            entry_checks={key: checks.get(key) for key in ("trend", "volume")},
        )
    losses = sum(value < 0 for value in pnl)
    mean_win = fmean(value for value in pnl if value > 0) if wins else None
    mean_loss = -fmean(value for value in pnl if value < 0) if losses else None
    return {
        "settings": settings,
        "metrics": account["metrics"],
        "trades": trades,
        "rounds": diag["rounds"],
        "completed": len(pnl),
        "wins": wins,
        "open": diag["open_rounds"],
        "win_rate": wins / len(pnl) if pnl else None,
        "mean_pnl": fmean(pnl) if pnl else None,
        "mean_win": mean_win,
        "mean_loss": mean_loss,
        "payoff": mean_win / mean_loss if mean_win is not None and mean_loss else None,
        "max_pnl": max(pnl, default=None),
        "time_in_market": diag["time_in_market"],
    }


def eligible(stats, minimum):
    """以完整轮次、精确胜负比例和净期望确认达标。"""
    return bool(
        stats
        and stats["completed"] >= minimum
        and 5 * stats["wins"] >= 4 * stats["completed"]
        and stats["mean_pnl"] > 0
    )


def summary(stats):
    return (
        {key: value for key, value in stats.items() if key not in ("rounds", "trades")}
        if stats
        else None
    )


def strength(results):
    """优先覆盖达到目标的代表 ETF，再比较交易样本和收益。"""
    rows = [stats for stats in results.values() if stats]
    return (
        sum(eligible(stats, TRAIN_MIN) for stats in rows),
        sum(
            stats["completed"] >= TRAIN_MIN
            and (stats["win_rate"] or 0) >= 0.70
            and stats["mean_pnl"] > 0
            for stats in rows
        ),
        sum((stats["wins"] + 2) / (stats["completed"] + 4) for stats in rows),
        sum(stats["metrics"]["total_return"] for stats in rows),
    )


def representatives(universe):
    """每个指数按训练期覆盖及成交额中位数确定一个代表。"""
    groups = defaultdict(list)
    for code, item in universe.items():
        sample = [row for row in item["rows"] if row["trade_date"] <= TRAIN_END][
            SHARED_WARMUP_BARS:
        ]
        if sample:
            groups[item["indices"][0]].append(
                (
                    len(sample),
                    median(
                        float(row["volume"]) * float(row["close"]) for row in sample
                    ),
                    code,
                )
            )
    return {index: max(members)[-1] for index, members in sorted(groups.items())}


def train_rounds(markets, codes):
    """依次运行基线与候选，阶段之间仅使用训练结果选择父规则。"""
    rounds = []

    def run(label, parent, rule=None, **changes):
        trial = {**parent, **changes, "rule": {**parent["rule"], **(rule or {})}}
        train = {
            code: summary(evaluate(markets[code], trial, "0001-01-01", TRAIN_END))
            for code in codes
        }
        number = len(rounds)
        entry = {
            "round": number,
            "label": label,
            "trial": trial,
            "train": train,
            "score": strength(train),
        }
        rounds.append(entry)
        print(f"第{number:02}轮 {label}，训练期达标 {entry['score'][0]} 只", flush=True)
        return trial

    run("现行基线", BASELINE)
    both = run("趋势和量能同过", BASELINE, {"buy_votes": 4})
    run("双门槛且量比至少1.1", both, {"volume_min": 1.1})
    run("双门槛加突破余量", both, filters={"margin": 0.2})
    run("双门槛加收盘位置与涨幅", both, filters={"position": 0.6, "impulse": 2.5})
    run("双门槛加均线方向与偏离", both, filters={"rising": True, "bias_max": 0.08})
    run("温和放量区间", both, {"volume_min": 1.1}, filters={"volume_max": 2.2})
    run("双门槛加压缩箱体", both, filters={"width": 0.10})
    run(
        "完整入场过滤",
        both,
        {"volume_min": 1.1},
        filters={
            "margin": 0.2,
            "position": 0.6,
            "impulse": 2.5,
            "rising": True,
            "bias_max": 0.08,
            "volume_max": 2.2,
        },
    )
    entry = max(rounds, key=lambda r: r["score"])["trial"]
    # 禁用止盈和期限的候选使用可序列化的不可达阈值。
    run("原入场取消固定止盈", BASELINE, {"take_profit": sys.maxsize})
    run("原入场取消强制到期", BASELINE, {"max_holding": sys.maxsize})
    run(
        "原入场同时取消止盈和到期",
        BASELINE,
        {"take_profit": sys.maxsize, "max_holding": sys.maxsize},
    )
    run("止盈2%", entry, {"take_profit": 0.02})
    run("止盈3%", entry, {"take_profit": 0.03})
    run("止盈4%", entry, {"take_profit": 0.04})
    run("止损2%", entry, {"stop_loss": 0.02})
    run(
        "止盈3%及止损4%持有15日",
        entry,
        {"take_profit": 0.03, "stop_loss": 0.04, "max_holding": 15},
    )
    run(
        "止盈4%及止损4%持有20日",
        entry,
        {"take_profit": 0.04, "stop_loss": 0.04, "max_holding": 20},
    )
    atr = run(
        "ATR分段跟踪及18日弱势退出", entry, atr_stop=2, atr_trail=2.5, atr_days=18
    )
    run("ATR初始止损1.5倍", atr, atr_stop=1.5)
    run("ATR初始止损2.5倍", atr, atr_stop=2.5)
    run("ATR跟踪放宽为3倍", atr, atr_trail=3)
    run("ATR加1.25倍波幅止盈", atr, atr_profit=1.25)
    run("ATR加1.75倍波幅止盈", atr, atr_profit=1.75)
    run("ATR叠加Wilder和20日分层风控", atr, layered=True)
    leader = max(rounds[1:], key=lambda r: r["score"])["trial"]
    run("领先规则冷静1日", leader, {"cooldown": 1})
    run("领先规则冷静5日", leader, {"cooldown": 5})
    run("领先规则10日突破", leader, {"break_window": 10})
    run("领先规则15日突破", leader, {"break_window": 15})
    run("领先规则40日突破", leader, {"break_window": 40})
    run("领先规则量比下限0.95", leader, {"volume_min": 0.95})
    assert len(rounds) == MAX_ROUNDS + 1
    return rounds


def write(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshot", type=Path, help="包含 input.json 与 manifest.json 的冻结目录"
    )
    parser.add_argument("output", type=Path, help="尚不存在的研究输出目录")
    args = parser.parse_args()
    raw = (args.snapshot / "input.json").read_bytes()
    source = json.loads((args.snapshot / "manifest.json").read_text())
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["input_sha256"]:
        raise ValueError("冻结行情摘要与清单不一致")
    universe = json.loads(raw)
    reps = representatives(universe)
    train_data = {
        code: prepare_market(
            {
                **item,
                "rows": [row for row in item["rows"] if row["trade_date"] <= TRAIN_END],
            },
            code,
        )
        for code, item in universe.items()
    }
    args.output.mkdir(parents=True, exist_ok=False)
    rounds = train_rounds(train_data, reps.values())
    selected = max(rounds[1:], key=lambda r: r["score"])
    fit = {
        code: evaluate(data, selected["trial"], "0001-01-01", TRAIN_END)
        for code, data in train_data.items()
    }
    qualified = sorted(
        code for code, result in fit.items() if eligible(result, TRAIN_MIN)
    )
    write(
        args.output / "training.json",
        {
            "input_sha256": digest,
            "engine": ENGINE_VERSION,
            "representatives": reps,
            "rounds": rounds,
            "selected": selected["round"],
            "training_qualified": qualified,
            "train_end": TRAIN_END,
            "train_min": TRAIN_MIN,
        },
    )
    print(f"锁定第{selected['round']:02}轮，开始留出检验", flush=True)
    records = {}
    for code, item in universe.items():
        market = prepare_market(item, code)
        fixed = evaluate(market, selected["trial"], HOLDOUT_START, HOLDOUT_END)
        baseline = evaluate(market, BASELINE, HOLDOUT_START, HOLDOUT_END)
        hold = evaluate(market, BASELINE, HOLDOUT_START, HOLDOUT_END, benchmark=True)
        records[code] = {
            "name": item["name"],
            "index": item["indices"][0],
            "train_base": evaluate(train_data[code], BASELINE, "0001-01-01", TRAIN_END),
            "train_selected": fit[code],
            "holdout_selected": fixed,
            "holdout_base": baseline,
            "holdout_benchmark": summary(hold),
            "excess": fixed["metrics"]["total_return"]
            - hold["metrics"]["total_return"],
            "drawdown_reduction": (
                1 - fixed["metrics"]["max_drawdown"] / hold["metrics"]["max_drawdown"]
                if hold["metrics"]["max_drawdown"]
                else None
            ),
            "passed": code in qualified and eligible(fixed, HOLDOUT_MIN),
        }
    passed = [code for code, stats in records.items() if stats["passed"]]
    write(
        args.output / "holdout.json",
        {
            "start": HOLDOUT_START,
            "end": HOLDOUT_END,
            "minimum": HOLDOUT_MIN,
            "passed": passed,
            "records": records,
        },
    )
    print(f"留出达标 {len(passed)} 只：{', '.join(passed) or '无'}", flush=True)


if __name__ == "__main__":
    main()
