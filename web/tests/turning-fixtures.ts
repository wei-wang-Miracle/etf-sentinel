// 合成行情只验证规则，不代表任何ETF的实际表现。
export function reversalRows() {
  let close = 12;
  const changes = [...Array(100).fill(-0.035), ...Array(12).fill(0.002), ...Array(85).fill(0.065), ...Array(80).fill(-0.07)];
  return changes.map((change, i) => {
    const open = close;
    close += change;
    return { date: new Date(Date.UTC(2025, 0, 1 + i)).toISOString().slice(0, 10), open, close,
      high: Math.max(open, close) + 0.01, low: Math.min(open, close) - 0.01,
      volume: 10000, change_pct: change / open * 100 };
  });
}
