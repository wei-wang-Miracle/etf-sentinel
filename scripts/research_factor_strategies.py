"""基于已冻结输入运行分类因子策略研究，不访问数据库或发布策略。"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="冻结目录中的input.json")
    parser.add_argument("output", type=Path, help="必须不存在的研究结果JSON")
    parser.add_argument("--rounds", type=int, default=50, help="确定性演化轮数，默认50")
    parser.add_argument("--seed", type=int, default=20261128, help="候选演化随机种子")
    parser.add_argument(
        "--eval-start-date",
        default=None,
        help="可选开发段正式评分起点 YYYY-MM-DD；默认读取冻结文件内 eval_start_date",
    )
    args = parser.parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    manifest_path = input_path.with_name("manifest.json")
    if output_path.exists():
        parser.error("研究结果文件已存在，不能覆盖")
    if not manifest_path.is_file():
        parser.error("冻结目录缺少manifest.json")

    from app.factor_strategy_research import run_research

    snapshot = json.loads(input_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("input_sha256") != digest(input_path):
        parser.error("冻结输入哈希与manifest不一致")
    if snapshot.get("version") not in (
        "factor-strategy-snapshot-v1.0.0",
        "factor-strategy-snapshot-v1.1.0",
        "factor-strategy-snapshot-v1.2.0",
    ):
        parser.error("冻结输入版本不受支持")
    universe = snapshot.get("universe")
    if not isinstance(universe, dict):
        parser.error("冻结输入缺少ETF集合")
    result = run_research(
        universe,
        rounds=args.rounds,
        random_seed=args.seed,
        eval_start_date=args.eval_start_date or snapshot.get("eval_start_date"),
    )
    result["input"] = {
        "path": str(input_path),
        "sha256": digest(input_path),
        "manifest_sha256": digest(manifest_path),
        "excluded": snapshot.get("excluded", {}),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        f"已完成每类别 {result['round_count']} 轮研究，生成 {len(result['candidates'])} 个候选，"
        f"覆盖 {len(result['category_leaders'])} 个类别；未发布策略。"
    )


if __name__ == "__main__":
    main()
