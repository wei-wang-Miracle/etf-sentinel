"""从已冻结的宽基 ETF 快照运行共享模板研究，不读数据库、不发布策略。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from app.backtest import ENGINE_VERSION
from app.shared_etf_fixed_prior import VERSION as FIXED_PRIOR_VERSION
from app.shared_etf_fixed_prior import run_fixed_prior
from app.shared_etf_research import RULES
from app.shared_etf_research import VERSION as WALK_FORWARD_VERSION
from app.shared_etf_walk_forward import (
    AXES,
    COSTS,
    DRAWDOWN_LIMIT,
    MAX_TAIL,
    MIN_PF,
    MIN_TRADES,
    STRESS,
    TRAIN_MIN_INDICES,
    TRAIN_MIN_TRADES,
    validate_split_cutoffs,
    walk_forward,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshot", type=Path, help="包含 input.json 与 manifest.json 的冻结目录"
    )
    parser.add_argument("output", type=Path, help="不存在的 JSON 输出文件")
    parser.add_argument(
        "--mode",
        choices=("fixed-prior", "walk-forward-v2.1"),
        default="fixed-prior",
        help="固定先验全期验收（默认）或保留的 v2.1 滚动寻优复现",
    )
    parser.add_argument(
        "--start",
        default="2026-01-01",
        help="仅 walk-forward-v2.1 使用的首个季度检验开始日期",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("研究输出已存在，不覆盖")
    raw = (args.snapshot / "input.json").read_bytes()
    manifest_raw = (args.snapshot / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest["input_sha256"]:
        raise ValueError("冻结输入摘要不一致")
    last = manifest["end"]
    universe = json.loads(raw)
    common = {
        "input_sha256": digest,
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "engine": ENGINE_VERSION,
        "eligible_for_release": False,
        "cutoff": last,
    }
    if args.mode == "fixed-prior":
        result = run_fixed_prior(universe, last)
        sources = [
            Path(__file__).resolve(),
            *(
                ROOT / "api/app" / f"{name}.py"
                for name in (
                    "shared_etf_fixed_prior",
                    "shared_etf_research",
                    "shared_etf_walk_forward",
                    "backtest",
                    "strategy_research",
                    "strategies",
                )
            ),
        ]
        report = {
            **common,
            "mode": args.mode,
            "version": FIXED_PRIOR_VERSION,
            "excluded_splits": validate_split_cutoffs(
                {code: universe[code] for code in result["representatives"]},
                result["period"]["start"],
            ),
            "unused_excluded_splits": {
                code: item["excluded_splits"]
                for code, item in universe.items()
                if code not in result["representatives"] and item["excluded_splits"]
            },
            "period_accounting": "65根预热后按代表初始一次建账，持仓、现金、分红、冷却和保护连续运行；不做滚动选参",
            "reference_accounting": "持有参照只在研究开始时建仓一次；闲置现金1.5%仅作不改变成交的辅助参考",
            "evidence": "中心参数、扰动轴和验收门槛预注册；冻结历史已被观察，不构成真正未见验证",
            "cross_asset": "目标标的缺失时明确未验证，不读取数据库或补采",
            **result,
        }
    else:
        sources = [
            Path(__file__).resolve(),
            *(
                ROOT / "api/app" / f"{name}.py"
                for name in (
                    "shared_etf_research",
                    "shared_etf_walk_forward",
                    "algorithm_templates",
                    "multifactor_research",
                    "strategies",
                    "backtest",
                    "strategy_research",
                )
            ),
        ]
        report = {
            **common,
            "mode": args.mode,
            "version": WALK_FORWARD_VERSION,
            "excluded_splits": validate_split_cutoffs(universe, args.start),
            "period_accounting": "初始一次建账，跨折保留仓位、资金、分红、冷却和入场时退出规则；只有训练子账户按折独立",
            "rule_effective": "新入场规则从当季首个有效收盘使用，未改写前一收盘目标",
            "trade_dividend_attribution": "已确认应收按登记日收盘仓位归属完整交易",
            "reference_accounting": "持有参照只在研究开始时建仓一次",
            "evidence": "滚动折内未参与选参，但冻结历史已被观察；不构成真正未见验证",
            "default_rules": RULES,
            "candidate_axes": AXES,
            "ordinary_costs": COSTS,
            "stress_costs": STRESS,
            "thresholds": {
                "train_trades": TRAIN_MIN_TRADES,
                "train_indices": TRAIN_MIN_INDICES,
                "release_trades": MIN_TRADES,
                "profit_factor": MIN_PF,
                "drawdown": DRAWDOWN_LIMIT,
                "tail_ratio": MAX_TAIL,
            },
            **walk_forward(universe, args.start, last),
        }
    report["sources"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sources
    }
    if any(
        hashlib.sha256(p.read_bytes()).hexdigest()
        != report["sources"][str(p.relative_to(ROOT))]
        for p in sources
    ):
        raise ValueError("运行期间研究代码已变化")
    with args.output.open("x") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    if args.mode == "fixed-prior":
        print(
            f"已记录固定先验全期研究（{report['period']['start']}至{report['period']['stop']}）；未发布策略。"
        )
    else:
        print(f"已记录 {len(report['folds'])} 折；未发布策略。")


if __name__ == "__main__":
    main()
