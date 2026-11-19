"""绘制冻结实验的K线、确认点和成交点，供逐轮复盘与最终交付。"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

plt.rcParams['font.family'] = ['Songti SC', 'Arial Unicode MS', 'sans-serif']
root = Path(sys.argv[1])
round_number = int(sys.argv[2])
group = sys.argv[3] if len(sys.argv) > 3 else None
if group:
    result = json.loads((root / 'final.json').read_text())['full'][group]
else:
    result = json.loads((root / f'round-{round_number:02d}-selected.json').read_text())
history = json.loads((root / 'qualified-history.json').read_text())
pairs = [(p['profit'], f['code'], p) for f in result['funds'] for p in f['pairs']]
pairs.sort(key=lambda row: row[0])
selected = [pairs[0], pairs[len(pairs)//2], pairs[-1]]
fig, axes = plt.subplots(3, 1, figsize=(14, 10), layout='constrained')
for ax, (_, code, pair) in zip(axes, selected):
    all_rows = history[code]['rows']
    start = next(i for i, r in enumerate(all_rows) if r['date'] == pair['entryDate'])
    end = next(i for i, r in enumerate(all_rows) if r['date'] == pair['exitDate'])
    rows = all_rows[max(0, start-20):end+11]
    dates = [r['date'] for r in rows]
    for i, row in enumerate(rows):
        color = '#b3382c' if row['close'] >= row['open'] else '#25744c'
        ax.vlines(i, row['low'], row['high'], color=color, linewidth=.7)
        ax.add_patch(Rectangle((i-.3, min(row['open'], row['close'])), .6, max(.0001, abs(row['close']-row['open'])), facecolor=color, linewidth=0))
    fund = next(f for f in result['funds'] if f['code'] == code)
    for signal in fund['signals']:
        if signal['date'] in dates:
            i = dates.index(signal['date'])
            ax.scatter(i, rows[i]['low']*.995 if signal['kind'] == 'bottom' else rows[i]['high']*1.005,
                       marker='^' if signal['kind'] == 'bottom' else 'v', color='#126594' if signal['kind'] == 'bottom' else '#9b650b', s=65, zorder=5)
    ax.axvline(dates.index(pair['entryDate']), color='#126594', linestyle='--', linewidth=.8, label='次日买入')
    ax.axvline(dates.index(pair['exitDate']), color='#9b650b', linestyle='--', linewidth=.8, label='次日卖出')
    ticks = list(range(0, len(rows), max(1, len(rows)//9)))
    ax.set_xticks(ticks, [rows[i]['date'] for i in ticks], rotation=15)
    label = f"{group}分类拟合" if group else f"第{round_number}轮"
    ax.set_title(f"{label} · {code} {fund['name']} · 净盈亏 {pair['profit']:+,.2f}元 · 持有{pair['holdingDays']}交易日", loc='left')
    ax.set_ylabel('价格／元'); ax.grid(axis='y', alpha=.15); ax.legend(loc='upper left')
filename = f'final-{group}-candles.png' if group else f'round-{round_number:02d}-candles.png'
fig.savefig(root / filename, dpi=150)
print(root / filename)
