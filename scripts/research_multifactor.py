"""冻结真实数据并运行最多50轮多因子信号研究，不写数据库或启用策略。"""

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.backtest import ENGINE_VERSION, simulate
from app.multifactor_research import (
    DEFAULT_RULE,
    VERSION,
    build_factors,
    prepare_signals,
)
from app.strategies import features
from app.strategy_research import diagnostics

DEFAULT_DIRECTORY = ROOT / ".local/multifactor-research/2026-11-18"
SETTINGS = {"initial_cash": 50000, "commission_rate": .0001,
            "minimum_commission": 0, "slippage_bps": 5}
GRID = {
    "family": ["bottom", "oversold", "pullback", "breakout", "hybrid"],
    "fast": [3, 5, 10, 15, 20], "slow": [20, 40, 60, 90, 120],
    "break_window": [3, 5, 10, 15, 20, 40], "rsi_window": [2, 5, 7, 14],
    "rsi_buy": [10, 20, 30, 40, 50], "dip": [0, .005, .01, .02, .03, .05],
    "trend_floor": [-.1, -.05, -.03, 0, .02], "recovery": [1, 3, 5],
    "volume_min": [.5, .8, 1, 1.2, 1.5], "event_age": [0, 2, 5, 10],
    "buy_votes": [2, 3, 4], "exit_ma": [3, 5, 10, 15, 20, 30],
    "rsi_sell": [60, 70, 80, 90], "sell_votes": [1, 2, 3],
    "stop_loss": [.03, .04, .05, .07, .1], "take_profit": [.015, .025, .04, .06, .1, .15],
    "trailing": [.02, .03, .05, .07, .1], "max_holding": [10, 15, 20, 30, 40, 60],
    "cooldown": [0, 3, 5, 10, 20],
    "value_metric": ["none", "pe_percentile", "pb_percentile"],
    "value_max": [30, 50, 70, 90, 100],
}


def write(path, value):
    """保存可人工审查的真实换行JSON。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def sha(path):
    """返回冻结文件的内容摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same_actions(left, right):
    """权益事件按业务日期比较，页面倒序与解析升序不算资料修订。"""
    return all(sorted(left[key], key=lambda e: json.dumps(e, sort_keys=True)) ==
               sorted(right[key], key=lambda e: json.dumps(e, sort_keys=True))
               for key in ("dividends", "splits"))


def freeze(directory):
    """只读提取本地行情、明确指数估值，并重新核验全部权益来源。"""
    from app.backtest_data import fetch_actions, trading_days, validate_market
    from app.db import Session, engine
    from app.models import Candle, InstrumentIndexLink
    from app.strategy_inputs import external_snapshot
    from dotenv import load_dotenv
    from sqlalchemy import select

    if (directory / "manifest.json").exists():
        raise ValueError("冻结目录已存在，不能覆盖研究输入")
    load_dotenv(ROOT / ".env")
    # db模块读取环境变量，命令入口已先加载本地环境。
    assert engine.url.host in ("localhost", "127.0.0.1", "::1")
    previous = ROOT / ".local/turning-research/2026-11-18-rerun"
    catalog = json.loads((previous / "qualified-history.json").read_text())
    groups = json.loads((previous / "classification.json").read_text())
    group_by_code = {c: key for key, g in groups.items() for c in g["codes"]}
    actions = {}
    def fetch_cached_on_failure(code):
        """远端临时不可用时由后续校验读取本地原始页面副本。"""
        try:
            return fetch_actions(code)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        fetched = dict(zip(catalog, pool.map(fetch_cached_on_failure, catalog), strict=True))
    for code, snapshot in fetched.items():
        if snapshot:
            snapshot["collected_at"] = snapshot["collected_at"].isoformat()
            actions[code] = snapshot
            continue
        saved = previous / f"actions-{code}.json"
        raw_saved = previous / f"actions-{code}-raw.html"
        cached = json.loads(saved.read_text()) if saved.exists() else None
        if cached and cached.get("source_html"):
            raw_html = cached["source_html"]
        elif raw_saved.exists():
            raw_html = raw_saved.read_text()
        else:
            raise ValueError(f"{code}当前权益源不可用，且没有可复核的缓存页面")
        from app.backtest_data import parse_actions
        reparsed = parse_actions(raw_html)
        if cached and not same_actions(cached["actions"], reparsed):
            raise ValueError(f"{code}缓存权益与原始页面复核不一致")
        actions[code] = {"actions": reparsed, "source_html": raw_html,
                         "source_sha256": hashlib.sha256(raw_html.encode()).hexdigest(),
                         "source_url": f"https://fundf10.eastmoney.com/fhsp_{code}.html",
                         "collected_at": cached.get("collected_at"),
                         "fallback_reason": "当前源不可用，使用此前研究保存的原始页面；原采集时间缺失时不猜测"}
    history, external_cache = {}, {}
    with Session() as db:
        db.connection().exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for code, item in catalog.items():
            records = list(db.scalars(select(Candle).where(Candle.code == code).order_by(Candle.date)))
            rows = [{"trade_date": str(r.date), **{k: str(getattr(r, k)) for k in (
                "open", "high", "low", "close", "volume", "adjusted_close")},
                "collected_at": r.collected_at.isoformat(), "source_updated_at": r.source_updated_at}
                for r in records]
            action = actions[code]
            splits = [e["effective_date"] for e in action["actions"]["splits"]
                      if rows[0]["trade_date"] <= e["effective_date"] <= rows[-1]["trade_date"]]
            post_split_rows = [r for r in rows if not splits or r["trade_date"] > max(splits)]
            try:
                validate_market(post_split_rows, action["actions"])
            except ValueError:
                # 数据源临时返回空表或权益修订与现有ADJUSTED_CLOSE冲突时，
                # 仅在此前保留的原始证据可重新解析且仍通过行情校验时回退。
                previous_actions = item["actions"]
                prior_json = previous / f"actions-{code}.json"
                prior_raw = previous / f"actions-{code}-raw.html"
                prior = json.loads(prior_json.read_text()) if prior_json.exists() else {}
                html = prior.get("source_html") or (prior_raw.read_text() if prior_raw.exists() else None)
                if not html:
                    raise
                from app.backtest_data import parse_actions
                if not same_actions(parse_actions(html), previous_actions):
                    raise ValueError(f"{code}旧权益页面与已冻结事件不一致") from None
                validate_market(post_split_rows, previous_actions)
                action = {"actions": previous_actions, "source_url": prior.get("source_url"),
                          "source_html": html, "source_sha256": hashlib.sha256(html.encode()).hexdigest(),
                          "collected_at": prior.get("collected_at"),
                          "fallback_reason": "当前源返回空表或与既有复权行情不符；使用已冻结原始页面"}
            write(directory / f"actions-{code}.json", action)
            rows = post_split_rows
            indices = list(db.scalars(select(InstrumentIndexLink.index_code).where(InstrumentIndexLink.instrument_code == code)))
            if len(indices) != 1:
                raise ValueError(f"{code}指数映射不唯一")
            key = (indices[0], rows[-1]["trade_date"])
            if key not in external_cache:
                rules = [{"buy": {"conditions": [{"indicator": "pe_percentile"}, {"indicator": "pb_percentile"}]}, "sell": {"conditions": []}}]
                external_cache[key] = external_snapshot(db, code, rules, date.fromisoformat(rows[-1]["trade_date"]))
            values = [float(v) for v, _ in features(rows, action["actions"]["dividends"], 2)]
            bars = [{"date": r["trade_date"], **{k: float(r[k]) * value / float(r["close"])
                     for k in ("open", "high", "low", "close")}}
                    for r, value in zip(rows, values, strict=True)]
            history[code] = {"name": item["name"], "group": group_by_code[code], "indices": indices,
                             "rows": rows, "actions": action["actions"], "factorRows": bars,
                             "external": external_cache[key], "calendar": trading_days(rows[0]["trade_date"], rows[-1]["trade_date"])[1],
                             "excluded_splits": splits}
    write(directory / "input.json", history)
    subprocess.run(["node", str(ROOT / "web/scripts/export-turning-factors.mjs"), str(directory)], check=True)
    source_files = ["api/app/multifactor_research.py", "api/app/backtest.py", "api/app/strategies.py",
                    "api/app/strategy_research.py", "api/app/backtest_data.py", "api/app/strategy_inputs.py",
                    "api/app/index_valuation.py", "web/src/lib/turningPoints.ts", "web/scripts/export-turning-factors.mjs",
                    "scripts/research_multifactor.py"]
    (directory / "source").mkdir(exist_ok=True)
    sources = {}
    for file in source_files:
        destination = directory / "source" / file.replace("/", "__")
        shutil.copyfile(ROOT / file, destination)
        sources[file] = sha(destination)
    write(directory / "manifest.json", {"version": VERSION, "engine": ENGINE_VERSION,
          "created_at": datetime.now(UTC).isoformat(), "input_sha256": sha(directory / "input.json"),
          "turning_sha256": sha(directory / "turning.json"), "sources": sources,
          "costs": SETTINGS, "max_rounds": 50, "target": .8,
          "evidence": "已观察历史拟合；估值是修订历史，延迟一交易日仍非原时点证据",
          "end": min(item["rows"][-1]["trade_date"] for item in history.values()),
          "coverage": {c: {"rows": len(v["rows"]), "first_decision": v["rows"][60]["trade_date"],
                            "excluded_splits": v["excluded_splits"]} for c, v in history.items()}})
    print("冻结完成：20只ETF，行情／权益／估值及算法摘要已保存", flush=True)


def evaluate(item, factors, rule, start=None, end=None, costs=None, full=False):
    """只执行汇总后的最终Decision，返回完整交易及期末持仓风险。"""
    rows = item["rows"]
    end = end or rows[-1]["trade_date"]
    decision_start = max(60, next((i - 1 for i, r in enumerate(rows) if r["trade_date"] >= start), 60)) if start else 60
    settings = {**SETTINGS, **(costs or {}), "end_date": end}
    signals = prepare_signals(rows, item["actions"]["dividends"], factors, rule, decision_start,
                              slippage_bps=settings["slippage_bps"])
    account = simulate(rows, item["actions"]["dividends"], settings, signals, decision_start + 1)
    rounds = diagnostics(account)["rounds"]
    positions = {r["trade_date"]: i for i, r in enumerate(rows)}
    buys = {t["trade_date"]: t for t in account["trades"] if t["side"] == "buy"}
    for pair in rounds:
        pair["pnl"] = float(pair["pnl"])
        pair["holding_days"] = positions[pair["exit_date"]] - positions[pair["entry_date"]]
        entry = buys[pair["entry_date"]]
        path = rows[positions[pair["entry_date"]]:positions[pair["exit_date"]] + 1]
        pair["mfe"] = max(float(r["high"]) / float(entry["price"]) - 1 for r in path)
    wins = sum(p["pnl"] > 0 for p in rounds)
    last = account["daily"][-1]
    opening = next(reversed(buys.values()), None) if last["quantity"] else None
    open_pnl = 0.
    if opening:
        income = sum(Decimal(e["amount"]) for e in account["dividends"] if e["kind"] == "receivable" and e["trade_date"] >= opening["trade_date"])
        open_pnl = float(Decimal(last["market_value"]) + income - Decimal(opening["notional"]) - Decimal(opening["commission"]))
    summary = {**account["metrics"], "trades": len(rounds), "wins": wins,
               "win_rate": wins / len(rounds) if rounds else None,
               "open_pnl": open_pnl, "open_quantity": last["quantity"],
               "max_holding": max((p["holding_days"] for p in rounds), default=0),
               "open_days": positions[last["trade_date"]] - positions[opening["trade_date"]] + 1 if opening else 0}
    result = {"rule": rule, "summary": summary, "rounds": rounds}
    if full:
        result.update(account=account, signals=[{"trade_date": r["trade_date"], "target": s["decision"].target,
                      "reason": s["decision"].reason, "indicators": s["indicators"]}
                      for r, s in zip(rows, signals, strict=True)])
    return result


def score(result):
    """优先有最低样本的80%目标，其次收益和回撤；不奖励额外亏损交易。"""
    s = result["summary"]
    if s["trades"] < 5:
        return -2 + .1 * s["trades"] + .05 * s["total_return"]
    return min(.8, s["win_rate"]) + .08 * min(.5, s["total_return"]) + .12 * s["max_drawdown"] - .2 * max(0, -s["open_pnl"] / 50000)


def aggregate(results):
    """按独立5万元账户加总，胜率按完整交易笔数加权。"""
    values = list(results.values())
    trades = sum(r["summary"]["trades"] for r in values)
    wins = sum(r["summary"]["wins"] for r in values)
    equity = sum(float(r["summary"]["final_equity"]) for r in values)
    return {"trades": trades, "wins": wins, "win_rate": wins / trades if trades else None,
            "final_equity": equity, "total_return": equity / (50000 * len(values)) - 1,
            "open_funds": sum(r["summary"]["open_quantity"] > 0 for r in values),
            "open_pnl": sum(r["summary"]["open_pnl"] for r in values),
            "qualified_funds": sum(r["summary"]["trades"] >= 5 and r["summary"]["win_rate"] >= .8 and r["summary"]["total_return"] > 0 for r in values)}


def diagnose(result):
    """亏损交易只进入下一轮研究诊断，不参与当日信号。"""
    losses = [p for p in result["rounds"] if p["pnl"] <= 0]
    return {"losses": len(losses), "quick": sum(p["holding_days"] <= 5 for p in losses),
            "gave_back": sum(p["mfe"] > .02 for p in losses),
            "focus": "exit" if sum(p["mfe"] > .02 for p in losses) > len(losses) / 2 else "entry"}


def run(directory, limit):
    """每轮全20只评估并依据各自亏损诊断调整，累计最多50轮。"""
    manifest = json.loads((directory / "manifest.json").read_text())
    for name, key in (("input.json", "input_sha256"), ("turning.json", "turning_sha256")):
        if sha(directory / name) != manifest[key]:
            raise ValueError("冻结输入摘要不符")
    for file, digest in manifest["sources"].items():
        if sha(ROOT / file) != digest:
            raise ValueError(f"研究期间算法已变化：{file}，须另建研究，不能混合轮次")
    history = json.loads((directory / "input.json").read_text())
    turning = json.loads((directory / "turning.json").read_text())
    factors = {c: build_factors(v["rows"], v["actions"]["dividends"],
               {s["date"]: s["kind"] for s in turning[c]["signals"]}, v["external"]) for c, v in history.items()}
    log = json.loads((directory / "rounds.json").read_text()) if (directory / "rounds.json").exists() else []
    incumbent = log[-1]["selected"] if log else {c: dict(DEFAULT_RULE) for c in history}
    cache = {}

    def cached(code, rule):
        key = (code, json.dumps(rule, sort_keys=True))
        if key not in cache:
            cache[key] = evaluate(history[code], factors[code], rule)
        return cache[key]

    while len(log) < limit:
        number = len(log) + 1
        rng = random.Random(20261118 + number * 1009)
        selected, candidates, before = {}, {}, {}
        for code in history:
            current = cached(code, incumbent[code])
            diagnosis = diagnose(current)
            before[code] = diagnosis
            proposals = [dict(incumbent[code])]
            if number == 1:
                proposals += [{**DEFAULT_RULE, "family": family} for family in GRID["family"]]
            focus = ["exit_ma", "sell_votes", "take_profit", "trailing", "max_holding"] if diagnosis["focus"] == "exit" else ["family", "rsi_buy", "dip", "trend_floor", "buy_votes", "recovery", "value_metric"]
            axis = focus[(number - 1) % len(focus)]
            proposals += [{**incumbent[code], axis: value} for value in GRID[axis]]
            for _ in range(6):
                rule = dict(incumbent[code])
                for field in rng.sample(list(GRID), 3 if number % 5 == 0 else 2):
                    rule[field] = rng.choice(GRID[field])
                proposals.append(rule)
            results = [cached(code, r) for r in proposals]
            best = max(results, key=lambda r: (score(r), r["summary"]["total_return"]))
            selected[code] = best
            candidates[code] = [{"rule": r["rule"], "summary": r["summary"], "score": score(r)} for r in results]
        incumbent = {c: r["rule"] for c, r in selected.items()}
        summary = aggregate(selected)
        record = {"round": number, "diagnosis_before": before, "candidates": candidates,
                  "selected": incumbent, "summary": summary,
                  "diagnosis_after": {c: diagnose(r) for c, r in selected.items()}}
        log.append(record)
        write(directory / "rounds.json", log)
        print(json.dumps({"round": number, **summary}, ensure_ascii=False), flush=True)
        if summary["qualified_funds"] == 20:
            break
    final = {c: evaluate(v, factors[c], incumbent[c], full=True) for c, v in history.items()}
    recent = {c: evaluate(v, factors[c], incumbent[c], start="2026-05-06") for c, v in history.items()}
    earlier = {c: evaluate(v, factors[c], incumbent[c], end="2026-04-30") for c, v in history.items()}
    costly = {c: evaluate(v, factors[c], incumbent[c], costs={"commission_rate": .0003, "minimum_commission": 5, "slippage_bps": 10}) for c, v in history.items()}
    write(directory / "final.json", {"rounds": len(log), "summary": aggregate(final), "funds": final,
          "recent": {"summary": aggregate(recent), "funds": recent},
          "earlier": {"summary": aggregate(earlier), "funds": earlier},
          "higher_cost": {"summary": aggregate(costly), "funds": costly}})
    print("最终账本、分段与费用敏感性已保存", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "run"])
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--rounds", type=int, default=50)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 50:
        parser.error("本轮上限必须在1至50轮")
    args.directory.mkdir(parents=True, exist_ok=True)
    if args.mode == "freeze":
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        freeze(args.directory)
    else:
        run(args.directory, args.rounds)
