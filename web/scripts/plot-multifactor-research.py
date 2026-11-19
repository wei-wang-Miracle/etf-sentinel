"""绘制汇总信号下最差、中位和最好完整交易的K线审查图。"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

root = Path(sys.argv[1])
final = json.loads((root / "final.json").read_text())
history = json.loads((root / "input.json").read_text())
turning = json.loads((root / "turning.json").read_text())
pairs = [(pair["pnl"], code, pair) for code, fund in final["funds"].items()
         for pair in fund["rounds"]]
pairs.sort(key=lambda item: item[0])
selected = [pairs[0], pairs[len(pairs) // 2], pairs[-1]]
plt.rcParams["font.family"] = ["Songti SC", "Arial Unicode MS", "sans-serif"]
fig, axes = plt.subplots(3, 1, figsize=(14, 10), layout="constrained")
for axis, (pnl, code, pair) in zip(axes, selected, strict=True):
    item = history[code]
    rows = item["rows"]
    first = next(i for i, row in enumerate(rows) if row["trade_date"] == pair["entry_date"])
    last = next(i for i, row in enumerate(rows) if row["trade_date"] == pair["exit_date"])
    left, right = max(0, first - 20), min(len(rows), last + 11)
    visible = rows[left:right]
    dates = [row["trade_date"] for row in visible]
    for index, row in enumerate(visible):
        color = "#b3382c" if float(row["close"]) >= float(row["open"]) else "#25744c"
        opening, closing = float(row["open"]), float(row["close"])
        axis.vlines(index, float(row["low"]), float(row["high"]), color=color, linewidth=.7)
        axis.add_patch(Rectangle((index - .3, min(opening, closing)), .6,
                                 max(.0001, abs(closing - opening)),
                                 facecolor=color, linewidth=0))
    fund = final["funds"][code]
    for signal in turning[code]["signals"]:
        if signal["date"] in dates:
            index = dates.index(signal["date"])
            row = visible[index]
            is_bottom = signal["kind"] == "bottom"
            axis.scatter(index, float(row["low"]) * .995 if is_bottom else float(row["high"]) * 1.005,
                         marker="^" if is_bottom else "v",
                         color="#126594" if is_bottom else "#9b650b", s=55, zorder=5)
    for signal in fund["signals"]:
        if signal["trade_date"] not in dates:
            continue
        index = dates.index(signal["trade_date"])
        if signal["reason"].startswith("汇总买入"):
            axis.scatter(index, float(visible[index]["low"]) * .985, marker="o",
                         color="#064c72", s=38, zorder=6)
        elif signal["reason"].startswith("汇总卖出"):
            axis.scatter(index, float(visible[index]["high"]) * 1.015, marker="x",
                         color="#b05d00", s=42, zorder=6)
    axis.axvline(dates.index(pair["entry_date"]), color="#126594", linestyle="--",
                 linewidth=.8, label="次日买入成交")
    axis.axvline(dates.index(pair["exit_date"]), color="#9b650b", linestyle="--",
                 linewidth=.8, label="次日卖出成交")
    ticks = list(range(0, len(visible), max(1, len(visible) // 9)))
    axis.set_xticks(ticks, [visible[index]["trade_date"] for index in ticks], rotation=15)
    axis.set_title(f"{code} {item['name']} · 完整交易净盈亏 {pnl:+,.2f} 元 · "
                   f"持有 {pair['holding_days']} 交易日", loc="left")
    axis.set_ylabel("价格／元")
    axis.grid(axis="y", alpha=.15)
    axis.legend(loc="upper left")
fig.savefig(root / "representative-trades.png", dpi=150)
print(root / "representative-trades.png")
