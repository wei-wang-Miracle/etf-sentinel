export const TURNING_VERSION = "slope-structure-paired-v3";
export type PriceBar = { date: string; open: number; high: number; low: number; close: number };
export type TurningKind = "bottom" | "top";
export type TurningSignal = {
  kind: TurningKind; date: string; dataCutoff: string; startedOn: string;
  level: number; invalidation: number; reason: string; version: string;
};
export type TurningPoint = {
  date: string; state: string; slope5?: number; slope20?: number; slope60?: number;
  signal?: TurningSignal;
};

export type TurningOptions = {
  backgroundDays: number;
  slopeThreshold: number;
  shortSlopeThreshold: number;
  breakoutWindow: number;
  breakoutAtrMultiplier: number;
  confirmationDays: number;
  cooldownDays: number;
  confirmationMaWindow: number;
  pairSignals: boolean;
  topMaWindow?: number;
  topBreakoutWindow?: number;
  topConfirmationDays?: number;
  topTrailingAtr?: number;
};

export const DEFAULT_TURNING_OPTIONS: TurningOptions = {
  backgroundDays: 3,
  slopeThreshold: 0.05,
  shortSlopeThreshold: 0.05,
  breakoutWindow: 10,
  breakoutAtrMultiplier: 0.2,
  confirmationDays: 1,
  cooldownDays: 10,
  confirmationMaWindow: 20,
  pairSignals: true,
};

// 不压缩坏记录，避免把缺失行情前后两段拼成连续交易日。
function segments(rows: readonly PriceBar[]): number[] {
  let segment = 0;
  return rows.map((row, i) => {
    const valid = [row.open, row.high, row.low, row.close].every(value => Number.isFinite(value) && value > 0)
      && row.low <= Math.min(row.open, row.close) && row.high >= Math.max(row.open, row.close)
      && Number.isFinite(Date.parse(row.date));
    if (!valid) { segment++; return -1; }
    if (i) {
      const gap = (Date.parse(row.date) - Date.parse(rows[i - 1].date)) / 86400000;
      if (!Number.isFinite(gap) || gap <= 0 || gap > 15) segment++;
    }
    return segment;
  });
}

function normalizedSlope(rows: readonly PriceBar[], volatility: number): number {
  if (!volatility) return 0;
  const center = (rows.length - 1) / 2;
  let numerator = 0, denominator = 0;
  rows.forEach((row, i) => {
    numerator += (i - center) * Math.log(row.close);
    denominator += (i - center) ** 2;
  });
  return numerator / denominator / volatility;
}

export function calculateTurningPoints(rows: readonly PriceBar[], partialOptions?: Partial<TurningOptions>, signalStart?: string): { points: TurningPoint[]; signals: TurningSignal[] } {
  const options = { ...DEFAULT_TURNING_OPTIONS, ...partialOptions };
  const topMaWindow = options.topMaWindow ?? options.confirmationMaWindow;
  const topBreakoutWindow = options.topBreakoutWindow ?? options.breakoutWindow;
  const topConfirmationDays = options.topConfirmationDays ?? options.confirmationDays;
  const topTrailingAtr = options.topTrailingAtr ?? 0;
  if (!Number.isFinite(topTrailingAtr) || topTrailingAtr < 0) throw new Error("无效顶部回落幅度");
  if ([topMaWindow, topBreakoutWindow, topConfirmationDays].some(value => !Number.isInteger(value) || value < 1 || value > 59)) throw new Error("无效顶部窗口");
  for (const key of ["backgroundDays", "breakoutWindow", "confirmationDays", "confirmationMaWindow"] as const) {
    if (!Number.isInteger(options[key]) || options[key] < 1 || options[key] > 59) throw new Error(`无效指标参数：${key}`);
  }
  for (const key of ["slopeThreshold", "shortSlopeThreshold", "breakoutAtrMultiplier", "cooldownDays"] as const) {
    if (!Number.isFinite(options[key]) || options[key] < 0) throw new Error(`无效指标参数：${key}`);
  }
  const ordered = [...rows].sort((left, right) => left.date.localeCompare(right.date));
  const ids = segments(ordered);
  const points: TurningPoint[] = [], signals: TurningSignal[] = [];
  const ranges: number[] = [];
  let start = 0, downDays = 0, upDays = 0;
  let bottomArmed = false, topArmed = false;
  let expectedKind: TurningKind = "bottom";
  let lastBottom = -Infinity, lastTop = -Infinity;
  let holdingHigh = 0;
  type Candidate = { index: number; level: number; invalidation: number };
  let bottom: Candidate | undefined, top: Candidate | undefined;
  for (let i = 0; i < ordered.length; i++) {
    const row = ordered[i];
    if (i === 0 || ids[i] < 0 || ids[i] !== ids[i - 1]) {
      start = i;
      downDays = upDays = 0;
      bottomArmed = topArmed = false;
      bottom = top = undefined;
      holdingHigh = 0;
      lastBottom = lastTop = -Infinity;
    }
    if (ids[i] < 0) {
      points.push({ date: row.date, state: "行情无效" });
      continue;
    }
    const previousClose = i > start ? ordered[i - 1].close : row.close;
    ranges[i] = Math.max(row.high - row.low, Math.abs(row.high - previousClose), Math.abs(row.low - previousClose));
    if (i - start < 59) {
      points.push({ date: row.date, state: "数据预热" });
      continue;
    }
    const atr = ranges.slice(i - 13, i + 1).reduce((sum, value) => sum + value, 0) / 14;
    const previousAtr = ranges.slice(i - 14, i).reduce((sum, value) => sum + value, 0) / 14;
    const slope = (window: number) => normalizedSlope(ordered.slice(i - window + 1, i + 1), atr / row.close);
    const slope5 = slope(5), slope20 = slope(20), slope60 = slope(60);
    const previous20 = normalizedSlope(ordered.slice(i - 20, i), previousAtr / previousClose);
    const maWindow = options.confirmationMaWindow;
    const ma20 = ordered.slice(i - maWindow + 1, i + 1).reduce((sum, value) => sum + value.close, 0) / maWindow;
    const previousMa20 = ma20 + (ordered[i - maWindow].close - row.close) / maWindow;
    downDays = slope20 <= -options.slopeThreshold ? downDays + 1 : 0;
    upDays = slope20 >= options.slopeThreshold ? upDays + 1 : 0;
    if (downDays === options.backgroundDays) bottomArmed = true;
    if (upDays === options.backgroundDays) topArmed = true;
    const prior = ordered.slice(i - options.breakoutWindow, i);
    const high = Math.max(...prior.map(value => value.high));
    const low = Math.min(...prior.map(value => value.low));
    const topPrior = ordered.slice(i - topBreakoutWindow, i);
    const topHigh = Math.max(...topPrior.map(value => value.high));
    const topLow = Math.min(...topPrior.map(value => value.low));
    const topMa = ordered.slice(i - topMaWindow + 1, i + 1).reduce((sum, value) => sum + value.close, 0) / topMaWindow;
    const previousTopMa = topMa + (ordered[i - topMaWindow].close - row.close) / topMaWindow;
    const bottomReady = atr > 0 && bottomArmed && i - lastBottom >= options.cooldownDays && slope5 > options.shortSlopeThreshold
      && slope20 > previous20 && row.close > ma20 && ma20 > previousMa20;
    const topReady = atr > 0 && topArmed && i - lastTop >= options.cooldownDays && slope5 < -options.shortSlopeThreshold
      && slope20 < previous20 && row.close < topMa && topMa < previousTopMa;
    if (expectedKind === "top") holdingHigh = Math.max(holdingHigh, row.high);
    const trailingLevel = holdingHigh - topTrailingAtr * atr;
    const trailingReady = topTrailingAtr > 0 && expectedKind === "top" && atr > 0
      && slope5 < -options.shortSlopeThreshold && row.close < trailingLevel;
    let signal: TurningSignal | undefined;
    if (bottom && (!bottomReady || row.close <= bottom.level)) bottom = undefined;
    if (top && (!topReady || row.close >= top.level)) top = undefined;
    const enabled = !signalStart || row.date >= signalStart;
    if (enabled && trailingReady) {
      signal = { kind: "top", date: row.date, dataCutoff: row.date, startedOn: row.date,
        level: trailingLevel, invalidation: holdingHigh, version: TURNING_VERSION,
        reason: `高点回落：底部确认后高点 ${holdingHigh.toFixed(3)} 回落至少${topTrailingAtr}ATR，5日斜率 ${slope5.toFixed(3)} < -${options.shortSlopeThreshold}；收盘确认，次日才可执行` };
      lastTop = i;
      topArmed = false;
    } else if (enabled && bottom && bottomReady && i - bottom.index >= options.confirmationDays && row.close > bottom.level
      && (!options.pairSignals || expectedKind === "bottom")) {
      signal = { kind: "bottom", date: row.date, dataCutoff: row.date, startedOn: ordered[bottom.index].date,
        level: bottom.level, invalidation: bottom.invalidation, version: TURNING_VERSION,
        reason: `此前下跌；5日斜率 ${slope5.toFixed(3)} > ${options.shortSlopeThreshold}，20日斜率改善，MA${maWindow}上行且收盘在其上，连续${options.confirmationDays + 1}日收于冻结突破价 ${bottom.level.toFixed(3)} 之上` };
      lastBottom = i;
      bottomArmed = false;
    } else if (enabled && top && topReady && i - top.index >= topConfirmationDays && row.close < top.level
      && (!options.pairSignals || expectedKind === "top")) {
      signal = { kind: "top", date: row.date, dataCutoff: row.date, startedOn: ordered[top.index].date,
        level: top.level, invalidation: top.invalidation, version: TURNING_VERSION,
        reason: `此前上涨；5日斜率 ${slope5.toFixed(3)} < -${options.shortSlopeThreshold}，20日斜率转弱，MA${topMaWindow}下行且收盘在其下，连续${topConfirmationDays + 1}日收于冻结突破价 ${top.level.toFixed(3)} 之下` };
      lastTop = i;
      topArmed = false;
    }
    // 冻结候选直到连续确认完成或条件失效，不能每天重置等待起点。
    if (!bottom && enabled && !signal && bottomReady && row.close > high + options.breakoutAtrMultiplier * atr) {
      bottom = { index: i, level: high + options.breakoutAtrMultiplier * atr, invalidation: low };
    }
    if (!top && enabled && !signal && topReady && row.close < topLow - options.breakoutAtrMultiplier * atr) {
      top = { index: i, level: topLow - options.breakoutAtrMultiplier * atr, invalidation: topHigh };
    }
    let state = "等待趋势";
    if (slope20 < -options.slopeThreshold) state = slope5 > 0 ? "底部候选" : slope20 > previous20 ? "下跌趋缓" : "下跌趋势";
    else if (slope20 > options.slopeThreshold) state = slope5 > 0.3 && row.close - ma20 > 2 * atr ? "急涨风险"
      : slope5 < 0 ? row.close < ma20 ? "顶部风险" : "回调观察" : "上升趋势";
    else if (bottomArmed && slope5 > 0) state = "底部候选";
    else if (topArmed && slope5 < 0) state = "顶部风险";
    if (bottom) state = "底部候选";
    if (top) state = "顶部风险";
    if (signal) {
      bottom = top = undefined;
      state = signal.kind === "bottom" ? "底部确认" : "顶部确认";
      signals.push(signal);
      expectedKind = signal.kind === "bottom" ? "top" : "bottom";
      holdingHigh = signal.kind === "bottom" ? row.high : 0;
    }
    points.push({ date: row.date, state, slope5, slope20, slope60, ...(signal ? { signal } : {}) });
  }
  return { points, signals };
}

export type DirectionStats = {
  total: number; evaluated: number; hits: number; pending: number; unavailable: number;
  meanReturn: number | null; baselineRate: number | null;
};

// 事后观察与信号计算分开，未来收盘只进入评估，不参与状态和确认。
export function evaluateTurningPoints(
  rows: readonly PriceBar[], signals: readonly TurningSignal[], start: string, end: string, horizon: number,
): Record<TurningKind, DirectionStats> {
  const eligible = [...rows].sort((left, right) => left.date.localeCompare(right.date)).filter(row => row.date <= end);
  const ids = segments(eligible);
  const indices = new Map(eligible.map((row, i) => [row.date, i]));
  const outcome = (i: number): number | "pending" | "unavailable" => {
    if (ids[i] < 0) return "unavailable";
    const last = Math.min(i + horizon, eligible.length - 1);
    for (let j = i + 1; j <= last; j++) if (ids[j] !== ids[i]) return "unavailable";
    if (i + horizon >= eligible.length) return "pending";
    return eligible[i + horizon].close / eligible[i].close - 1;
  };
  const baseline = eligible.flatMap((row, i) => {
    if (row.date < start) return [];
    const value = outcome(i);
    return typeof value === "number" ? [value] : [];
  });
  const stats = (kind: TurningKind): DirectionStats => {
    const selected = signals.filter(signal => signal.kind === kind && signal.date >= start && signal.date <= end);
    const returns: number[] = [];
    let pending = 0, unavailable = 0;
    for (const signal of selected) {
      const index = indices.get(signal.date);
      const value = index == null ? "unavailable" : outcome(index);
      if (value === "pending") pending++;
      else if (value === "unavailable") unavailable++;
      else returns.push(value);
    }
    const hit = (value: number) => kind === "bottom" ? value > 0 : value < 0;
    return { total: selected.length, evaluated: returns.length, hits: returns.filter(hit).length, pending, unavailable,
      meanReturn: returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : null,
      baselineRate: baseline.length ? baseline.filter(hit).length / baseline.length : null };
  };
  return { bottom: stats("bottom"), top: stats("top") };
}

export type SimulationTrade = {
  side: "buy" | "sell";
  signalDate: string;
  tradeDate: string;
  price: number;
  quantity: number;
  notional: number;
  commission: number;
};

export type SimulationResult = {
  initialCash: number;
  finalEquity: number;
  totalReturn: number;
  maxDrawdown: number;
  trades: SimulationTrade[];
  completedTrades: number;
  winningTrades: number;
  pendingSignals: number;
  ignoredSignals: number;
  openQuantity: number;
  openProfit: number;
  daily: { date: string; cash: number; quantity: number; equity: number; drawdown: number }[];
  pairs: { entryDate: string; exitDate: string; profit: number; return: number; holdingDays: number; entrySignalDate: string; exitSignalDate: string }[];
};

export type SimulationOptions = {
  initialCash?: number;
  lotSize?: number;
  commissionRate?: number;
  minimumCommission?: number;
  slippageBps?: number;
};

// 信号在收盘后才知道，因此统一在下一条行情的开盘执行；只接受底部到顶部的成对交易。
export function simulateTurningStrategy(
  rows: readonly PriceBar[], signals: readonly TurningSignal[], partialOptions?: SimulationOptions,
): SimulationResult {
  const options = {
    initialCash: 50000,
    lotSize: 100,
    commissionRate: 0.0001,
    minimumCommission: 0,
    slippageBps: 5,
    ...partialOptions,
  };
  const ordered = [...rows].sort((left, right) => left.date.localeCompare(right.date));
  if (segments(ordered).some((id, i, ids) => id < 0 || (i > 0 && id !== ids[i - 1]))) {
    throw new Error("模拟行情存在无效价格、重复日期或长断档");
  }
  if (!(options.initialCash > 0) || !Number.isInteger(options.lotSize) || options.lotSize < 1
    || [options.commissionRate, options.minimumCommission, options.slippageBps].some(value => !Number.isFinite(value) || value < 0)
    || options.slippageBps >= 10000) throw new Error("无效模拟参数");
  const signalByDate = new Map<string, TurningSignal>();
  for (const signal of signals) {
    if (signalByDate.has(signal.date)) throw new Error("同一天存在多个信号");
    if (signal.dataCutoff > signal.date) throw new Error("信号使用了未来数据");
    signalByDate.set(signal.date, signal);
  }
  const money = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;
  let cash = money(options.initialCash), quantity = 0, entryCost = 0;
  let peak = cash, maxDrawdown = 0, pendingSignals = 0, ignoredSignals = 0;
  let entryIndex = 0, entrySignalDate = "";
  const trades: SimulationTrade[] = [];
  const daily: SimulationResult["daily"] = [], pairs: SimulationResult["pairs"] = [];
  for (let i = 0; i < ordered.length; i++) {
    const row = ordered[i];
    // 当日开盘只执行上一日收盘已知信号，之后才按当日收盘估值。
    const signal = i > 0 ? signalByDate.get(ordered[i - 1].date) : undefined;
    if (signal) {
      const side = signal.kind === "bottom" && !quantity ? "buy" : signal.kind === "top" && quantity ? "sell" : undefined;
      if (!side) ignoredSignals++;
      else {
        const rawTicks = row.open * (1 + (side === "buy" ? 1 : -1) * options.slippageBps / 10000) * 1000;
        const price = (side === "buy" ? Math.ceil(rawTicks - 1e-9) : Math.floor(rawTicks + 1e-9)) / 1000;
        let count = side === "sell" ? quantity : Math.floor(cash / (price * options.lotSize)) * options.lotSize;
        const fee = (count: number) => money(Math.max(options.minimumCommission, money(price * count) * options.commissionRate));
        while (side === "buy" && count > 0 && money(price * count) + fee(count) > cash + 1e-8) count -= options.lotSize;
        if (!count) ignoredSignals++;
        else {
          const notional = money(price * count), commission = fee(count);
          if (side === "buy") {
            cash = money(cash - notional - commission);
            quantity = count;
            entryCost = money(notional + commission);
            entryIndex = i;
            entrySignalDate = signal.date;
          } else {
            const proceeds = money(notional - commission);
            cash = money(cash + proceeds);
            pairs.push({ entryDate: ordered[entryIndex].date, exitDate: row.date,
              profit: money(proceeds - entryCost), return: proceeds / entryCost - 1,
              holdingDays: i - entryIndex, entrySignalDate, exitSignalDate: signal.date });
            quantity = 0;
            entryCost = 0;
          }
          trades.push({ side, signalDate: signal.date, tradeDate: row.date, price, quantity: count, notional, commission });
        }
      }
    }
    const equity = money(cash + quantity * row.close);
    peak = Math.max(peak, equity);
    const drawdown = equity / peak - 1;
    maxDrawdown = Math.min(maxDrawdown, drawdown);
    daily.push({ date: row.date, cash, quantity, equity, drawdown });
  }
  if (ordered.length && signalByDate.has(ordered.at(-1)!.date)) pendingSignals++;
  const finalEquity = daily.at(-1)?.equity ?? cash;
  return { initialCash: options.initialCash, finalEquity, totalReturn: finalEquity / options.initialCash - 1,
    maxDrawdown, trades, completedTrades: pairs.length, winningTrades: pairs.filter(pair => pair.profit > 0).length,
    pendingSignals, ignoredSignals, openQuantity: quantity,
    openProfit: quantity ? money(quantity * ordered.at(-1)!.close - entryCost) : 0, daily, pairs };
}
