import { test, expect } from "@playwright/test";
import { calculateTurningPoints, evaluateTurningPoints, simulateTurningStrategy, type TurningSignal } from "../src/lib/turningPoints";
import { reversalRows } from "./turning-fixtures";

const manualSignal = (date: string, kind: "bottom" | "top"): TurningSignal => ({
  kind, date, dataCutoff: date, startedOn: date, level: 10, invalidation: 9, reason: "账本测试", version: "test",
});

test("次日开盘成交，跳空不改变信号当天现金与净值", () => {
  const rows = [
    { date: "2026-01-05", open: 10, high: 10, low: 10, close: 10 },
    { date: "2026-01-06", open: 20, high: 22, low: 20, close: 22 },
    { date: "2026-01-07", open: 21, high: 21, low: 21, close: 21 },
  ];
  const result = simulateTurningStrategy(rows, [manualSignal(rows[0].date, "bottom"), manualSignal(rows[1].date, "top")], { commissionRate: 0, slippageBps: 0 });
  expect(result.daily[0]).toMatchObject({ cash: 50000, quantity: 0, equity: 50000 });
  expect(result.daily[1]).toMatchObject({ cash: 0, quantity: 2500, equity: 55000 });
  expect(result.finalEquity).toBe(52500);
  expect(result.pairs[0]).toMatchObject({ profit: 2500, entryDate: rows[1].date, exitDate: rows[2].date });
  expect(result.maxDrawdown).toBeCloseTo(52500 / 55000 - 1);
});

test("整手购买预留费用，价格按最小变动单位朝不利方向取整", () => {
  const rows = [0, 1, 2].map(i => ({ date: `2026-01-0${5 + i}`, open: 10, high: 10, low: 10, close: 10 }));
  const result = simulateTurningStrategy(rows, [manualSignal(rows[0].date, "bottom")], { slippageBps: 0, minimumCommission: 5 });
  expect(result.trades[0].quantity).toBe(4900);
  expect(result.daily.every(day => day.cash >= 0)).toBe(true);
  expect(result.openQuantity).toBe(4900);
  expect(result.completedTrades).toBe(0);
  expect(result.openProfit).toBe(-5);
  const tick = simulateTurningStrategy(rows, [manualSignal(rows[0].date, "bottom"), manualSignal(rows[1].date, "top")], { slippageBps: 0.1 });
  expect(tick.trades.map(trade => trade.price)).toEqual([10.001, 9.999]);
  expect(simulateTurningStrategy([], []).finalEquity).toBe(50000);
});

test("多日候选保持冻结价，等待足够天数才确认", () => {
  const rows = reversalRows();
  const result = calculateTurningPoints(rows, { confirmationDays: 3 });
  expect(result.signals.map(signal => signal.kind)).toEqual(["bottom", "top"]);
  for (const signal of result.signals) {
    const begin = rows.findIndex(row => row.date === signal.startedOn);
    const end = rows.findIndex(row => row.date === signal.date);
    expect(end - begin).toBe(3);
    expect(rows.slice(begin, end + 1).every(row => signal.kind === "bottom" ? row.close > signal.level : row.close < signal.level)).toBe(true);
  }
});

test("顶部窗口可独立缩短，底部日期不变且顶部不读取未来", () => {
  const rows = reversalRows();
  const original = calculateTurningPoints(rows);
  const option = { topMaWindow: 5, topBreakoutWindow: 3, topConfirmationDays: 1 };
  const faster = calculateTurningPoints(rows, option);
  expect(faster.signals[0].date).toBe(original.signals[0].date);
  expect(faster.signals[1].date < original.signals[1].date).toBe(true);
  const end = rows.findIndex(row => row.date === faster.signals[1].date) + 1;
  expect(calculateTurningPoints(rows.slice(0, end), option).signals).toEqual(faster.signals);
});

test("高点回落顶部独立于是否盈利，短斜率转负后提前确认", () => {
  const rows = reversalRows();
  const original = calculateTurningPoints(rows, { topMaWindow: 30 });
  const options = { topMaWindow: 30, topTrailingAtr: 1 };
  const faster = calculateTurningPoints(rows, options);
  expect(faster.signals[1].date < original.signals[1].date).toBe(true);
  expect(faster.signals[1].reason).toContain("高点回落");
  for (let length = 60; length <= rows.length; length++) {
    expect(calculateTurningPoints(rows.slice(0, length), options).signals).toEqual(faster.signals.filter(s => s.date <= rows[length - 1].date));
  }
});

test("区间从空仓重启配对，预热不使用区间之后的数据", () => {
  const rows = reversalRows();
  const start = rows[150].date;
  expect(calculateTurningPoints(rows, undefined, start).signals).toEqual([]);
  const broken = [...rows.slice(0, 150), ...rows.slice(150).map(row => ({ ...row, date: new Date(Date.parse(row.date) + 30 * 86400000).toISOString().slice(0, 10) }))];
  const signals = calculateTurningPoints(broken).signals;
  expect(signals.every((signal, i) => signal.kind === (i % 2 ? "top" : "bottom"))).toBe(true);
});

test("持续下跌再反转和上涨再反转，产生两类确认且不每天重复", () => {
  const rows = reversalRows();
  const { points, signals } = calculateTurningPoints(rows);
  expect(signals.map(row => row.kind)).toEqual(["bottom", "top"]);
  expect(signals.every((signal, index) => signal.kind === (index % 2 === 0 ? "bottom" : "top"))).toBe(true);
  expect(Date.parse(signals[0].date)).toBeGreaterThan(Date.parse(rows[111].date));
  expect(Date.parse(signals[1].date)).toBeGreaterThan(Date.parse(rows[196].date));
  expect(points.filter(row => row.state === "底部确认")).toHaveLength(1);
  for (const signal of signals) {
    const index = rows.findIndex(row => row.date === signal.date);
    expect(signal.startedOn).toBe(rows[index - 1].date);
    expect(signal.dataCutoff).toBe(signal.date);
    if (signal.kind === "bottom") {
      expect(rows[index - 1].close).toBeGreaterThan(signal.level);
      expect(rows[index].close).toBeGreaterThan(signal.level);
    } else {
      expect(rows[index - 1].close).toBeLessThan(signal.level);
      expect(rows[index].close).toBeLessThan(signal.level);
    }
  }
});

test("逐日截断和追加未来行情不改变已发生的状态、日期及依据", () => {
  const rows = reversalRows();
  const full = calculateTurningPoints(rows);
  for (let length = 60; length <= rows.length; length++) {
    const prefix = calculateTurningPoints(rows.slice(0, length));
    expect(prefix.points).toEqual(full.points.slice(0, length));
    expect(prefix.signals).toEqual(full.signals.filter(row => row.date <= rows[length - 1].date));
  }
});

test("无论行情按何种顺序传入，先按日期升序计算信号与事后统计", () => {
  const rows = reversalRows();
  const ordered = calculateTurningPoints(rows);
  const reversed = calculateTurningPoints([...rows].reverse());
  expect(reversed).toEqual(ordered);
  const orderedStats = evaluateTurningPoints(rows, ordered.signals, rows[0].date, rows.at(-1)!.date, 10);
  const reversedStats = evaluateTurningPoints([...rows].reverse(), ordered.signals, rows[0].date, rows.at(-1)!.date, 10);
  expect(reversedStats).toEqual(orderedStats);
});

test("参数变化进入同一计算引擎，模拟只接受底部到顶部的成对交易", () => {
  const rows = reversalRows();
  const defaultResult = calculateTurningPoints(rows);
  const strictResult = calculateTurningPoints(rows, { backgroundDays: 5, breakoutWindow: 15, confirmationDays: 2, confirmationMaWindow: 10 });
  expect(strictResult.signals).not.toEqual(defaultResult.signals);
  const result = simulateTurningStrategy(rows, defaultResult.signals, { initialCash: 50000, slippageBps: 0, commissionRate: 0 });
  expect(result.trades.every(trade => trade.side === "buy" || trade.side === "sell")).toBe(true);
  expect(result.trades.filter(trade => trade.side === "buy").length).toBe(result.trades.filter(trade => trade.side === "sell").length);
  expect(result.completedTrades).toBe(result.trades.length / 2);
  expect(result.initialCash).toBe(50000);
  expect(Number.isFinite(result.finalEquity)).toBe(true);
});

test("不足60条预热、平盘和单日假突破不产生确认", () => {
  const rows = reversalRows();
  expect(calculateTurningPoints(rows.slice(0, 59)).signals).toEqual([]);
  const flat = rows.map(row => ({ ...row, open: 5, high: 5, low: 5, close: 5 }));
  expect(calculateTurningPoints(flat).signals).toEqual([]);
  const spike = rows.slice(0, 100);
  spike.push({ ...rows[100], open: 8.5, high: 20.1, low: 8.4, close: 20 });
  spike.push({ ...rows[101], open: 8.5, high: 8.6, low: 8.3, close: 8.4 });
  expect(calculateTurningPoints(spike).signals).toEqual([]);
});

test("坏行情和长断档重新预热，不跨断档确认", () => {
  const rows = reversalRows();
  const first = calculateTurningPoints(rows).signals[0];
  const index = rows.findIndex(row => row.date === first.date);
  const broken = rows.slice(0, index + 1).map((row, i) => i === index - 1 ? { ...row, close: NaN } : row);
  const result = calculateTurningPoints(broken);
  expect(result.signals).toEqual([]);
  expect(result.points[index - 1].state).toBe("行情无效");
  expect(result.points[index].state).toBe("数据预热");
  const gap = rows.slice(0, index + 1).map((row, i) => i === index ? { ...row, date: "2026-11-01" } : row);
  expect(calculateTurningPoints(gap).points.at(-1)?.state).toBe("数据预热");
});

test("新一轮下跌再反转可再次确认，同方向至少间隔10条记录", () => {
  const first = reversalRows();
  const offset = first.at(-1)!.close - first[0].open;
  const second = reversalRows().map((row, i) => ({ ...row, open: row.open + offset, close: row.close + offset,
    high: row.high + offset, low: row.low + offset,
    date: new Date(Date.UTC(2025, 0, 1 + i + first.length)).toISOString().slice(0, 10) }));
  const rows = [...first, ...second];
  const signals = calculateTurningPoints(rows).signals;
  expect(signals.filter(row => row.kind === "bottom")).toHaveLength(2);
  for (const kind of ["bottom", "top"]) {
    const indices = signals.filter(row => row.kind === kind).map(signal => rows.findIndex(row => row.date === signal.date));
    for (let i = 1; i < indices.length; i++) expect(indices[i] - indices[i - 1]).toBeGreaterThanOrEqual(10);
  }
});

test("事后方向检验区分命中、持平、待观察和断档，不越过显示截止日", () => {
  const rows = reversalRows().slice(0, 8).map((row, i) => ({ ...row, open: 5 + i, high: 6 + i, low: 4 + i, close: 5 + i }));
  rows[2] = { ...rows[2], low: 4, close: 5 };
  const signal = (index: number, kind: "bottom" | "top"): TurningSignal => ({
    kind, date: rows[index].date, dataCutoff: rows[index].date, startedOn: rows[index].date,
    level: 5, invalidation: 4, reason: "合成测试", version: "slope-structure-v1",
  });
  // 首个样本持平，第二个上涨，末尾样本观察期不足。
  const signals = [signal(0, "bottom"), signal(3, "bottom"), signal(6, "bottom"), signal(3, "top")];
  const result = evaluateTurningPoints(rows, signals, rows[0].date, rows[7].date, 2);
  expect(result.bottom).toMatchObject({ total: 3, evaluated: 2, hits: 1, pending: 1, unavailable: 0 });
  expect(result.top).toMatchObject({ total: 1, evaluated: 1, hits: 0 });
  expect(result.bottom.meanReturn).toBeCloseTo((0 + (10 / 8 - 1)) / 2);
  const shorter = evaluateTurningPoints(rows, signals, rows[3].date, rows[4].date, 2);
  expect(shorter.bottom).toMatchObject({ total: 1, evaluated: 0, hits: 0, pending: 1, meanReturn: null });
  const broken = rows.map((row, i) => i === 4 ? { ...row, close: 0 } : row);
  expect(evaluateTurningPoints(broken, signals, rows[0].date, rows[7].date, 2).bottom.unavailable).toBe(1);
  expect(evaluateTurningPoints(rows, [], rows[0].date, rows[7].date, 2).bottom.meanReturn).toBeNull();
});
