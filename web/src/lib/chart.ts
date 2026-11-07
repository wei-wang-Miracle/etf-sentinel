import type { Trade } from "./backtests";

export const MA_WINDOWS = [5, 10, 20, 30, 60] as const;
export const MA_LINE_WIDTH: Record<number, number> = {
  5: 1,
  10: 1.4,
  20: 1,
  30: 1.4,
  60: 1,
};

export type ChartPalette = {
  up: string;
  down: string;
  ink: string;
  muted: string;
  border: string;
  surface: string;
  primarySoft: string;
  chart1: string;
  chart2: string;
  chart3: string;
  chart4: string;
  chart5: string;
  chart6: string;
  fear: string;
  greed: string;
  ma: Record<number, string>;
  fontFamily: string;
};

export function readChartPalette(): ChartPalette {
  const styles = getComputedStyle(document.documentElement);
  const color = (name: string) =>
    styles.getPropertyValue(`--color-${name}`).trim();
  return {
    up: color("market-up"),
    down: color("market-down"),
    ink: color("ink"),
    muted: color("ink-muted"),
    border: color("border"),
    surface: color("surface-elevated"),
    primarySoft: color("primary-soft"),
    chart1: color("chart-1"),
    chart2: color("chart-2"),
    chart3: color("chart-3"),
    chart4: color("chart-4"),
    chart5: color("chart-5"),
    chart6: color("chart-6"),
    fear: color("sentiment-fear"),
    greed: color("sentiment-greed"),
    ma: {
      5: color("ma-5"),
      10: color("ma-10"),
      20: color("ma-20"),
      30: color("ma-30"),
      60: color("ma-60"),
    },
    fontFamily:
      styles.getPropertyValue("--font-chart").trim() ||
      '"PingFang SC", "Microsoft YaHei", monospace',
  };
}

export function movingAverage(
  values: number[],
  window: number,
): (number | null)[] {
  const result: (number | null)[] = [];
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= window) sum -= values[index - window];
    result.push(index >= window - 1 ? sum / window : null);
  }
  return result;
}

export const formatPrice = (value: number) => value.toFixed(3);

export const chartStamp = () =>
  new Date().toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
  });

export const formatCompact = (value: number) =>
  new Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);

export function escapeHtml(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });
}

export type TradeMarker = {
  trade_date: string;
  side: string;
  price: number;
  count: number;
  tradeIndex: number;
  paired: boolean;
  notional: number;
};

export function aggregateTradeMarkers(
  trades: Trade[],
  maxMarkers = 20,
): TradeMarker[] {
  const paired = new Set<number>();
  const openBuys: number[] = [];
  trades.forEach((trade, index) => {
    if (trade.side === "buy") {
      openBuys.push(index);
    } else if (trade.side === "sell" && openBuys.length) {
      const buy = openBuys.shift();
      if (buy != null) {
        paired.add(buy);
        paired.add(index);
      }
    }
  });

  const groups = new Map<string, TradeMarker>();
  trades.forEach((trade, index) => {
    const price = Number(trade.price);
    const quantity = Number(trade.quantity);
    const key = `${trade.trade_date}|${trade.side}`;
    const existing = groups.get(key);
    if (existing) {
      existing.count += 1;
      existing.notional += price * quantity;
      existing.price = price;
      existing.tradeIndex = index;
      existing.paired = existing.paired || paired.has(index);
      return;
    }
    groups.set(key, {
      trade_date: trade.trade_date,
      side: trade.side,
      price,
      count: 1,
      tradeIndex: index,
      paired: paired.has(index),
      notional: price * quantity,
    });
  });

  const markers = [...groups.values()];
  if (markers.length <= maxMarkers) return markers;
  return markers
    .map((marker, index) => ({ marker, index }))
    .sort(
      (left, right) =>
        Number(right.marker.paired) - Number(left.marker.paired) ||
        right.marker.trade_date.localeCompare(left.marker.trade_date) ||
        right.marker.notional - left.marker.notional,
    )
    .slice(0, maxMarkers)
    .sort((left, right) => left.index - right.index)
    .map(({ marker }) => marker);
}
