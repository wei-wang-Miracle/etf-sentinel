import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { CandlestickChart, BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  MarkPointComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  MarkPointComponent,
  CanvasRenderer,
]);
import type { Candle } from "../lib/api";
import {
  MA_LINE_WIDTH,
  MA_WINDOWS,
  escapeHtml,
  formatCompact,
  formatPrice,
  movingAverage,
  readChartPalette,
} from "../lib/chart";

export default function KLine({
  rows,
  theme,
  holdings,
  indexPoints = false,
  trades = [],
}: {
  indexPoints?: boolean;
  trades?: { trade_date: string; side: string; quantity: string; price: string }[];
  rows: Candle[];
  theme: string;
  holdings?: { trade_date: string; estimated_holding_pct: number | null }[];
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || (!rows.length && !holdings?.length)) return;
    const chart = echarts.init(element.current);
    const palette = readChartPalette();
    const comparison = holdings !== undefined;
    const holdingRows = holdings ?? [];
    const dates = comparison
      ? [
          ...new Set([
            ...rows.map((r) => r.date),
            ...holdingRows.map((r) => r.trade_date),
          ]),
        ].sort()
      : rows.map((r) => r.date);
    const candleByDate = new Map(rows.map((r) => [r.date, r]));
    const holdingByDate = new Map(
      holdingRows.map((r) => [r.trade_date, r.estimated_holding_pct]),
    );
    const maByDate = new Map<string, Record<number, number>>();
    MA_WINDOWS.forEach((window) => {
      const values = movingAverage(
        rows.map((r) => r.close),
        window,
      );
      rows.forEach((row, index) => {
        const value = values[index];
        if (value == null) return;
        const entry = maByDate.get(row.date) ?? {};
        entry[window] = value;
        maByDate.set(row.date, entry);
      });
    });
    const maSeries = MA_WINDOWS.map((window) => ({
      window,
      data: dates.map((day) => maByDate.get(day)?.[window] ?? null),
    })).filter((series) => series.data.some((value) => value != null));
    const percent = (value: number | null | undefined) =>
      value == null
        ? "—"
        : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
    const tone = (value: number | null | undefined) =>
      value == null ? palette.muted : value >= 0 ? palette.up : palette.down;
    const tooltip = (raw: unknown) => {
      const list = raw as Array<{ axisValue?: string }>;
      const day = list[0]?.axisValue ?? "";
      const candle = candleByDate.get(day);
      const holding = holdingByDate.get(day);
      const lines = [
        `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(day)}</div>`,
      ];
      if (candle) {
        lines.push(
          `<div style="display:flex;gap:12px;white-space:nowrap">` +
            `<span>开 ${formatPrice(candle.open)}</span>` +
            `<span>高 ${formatPrice(candle.high)}</span>` +
            `<span>低 ${formatPrice(candle.low)}</span>` +
            `<span style="color:${tone(candle.close - candle.open)}">收 ${formatPrice(candle.close)}</span>` +
            `</div>`,
          `<div>涨跌幅 <span style="color:${tone(candle.change_pct)}">${percent(candle.change_pct)}</span>` +
            `　成交量 ${formatCompact(candle.volume)}</div>`,
        );
      } else {
        lines.push(`<div style="color:${palette.muted}">该日无本地日 K</div>`);
      }
      const maItems = MA_WINDOWS.flatMap((window) => {
        const value = maByDate.get(day)?.[window];
        return value == null
          ? []
          : [
              `<span style="color:${palette.ma[window]}">MA${window} ${formatPrice(value)}</span>`,
            ];
      });
      if (maItems.length) {
        lines.push(
          `<div style="display:flex;gap:10px;flex-wrap:wrap">${maItems.join("")}</div>`,
        );
      }
      if (comparison) {
        lines.push(
          `<div style="margin-top:3px">国家队估算持仓比例 <span style="color:${palette.chart2}">${holding == null ? "—" : `${holding.toFixed(2)}%`}</span></div>`,
        );
      }
      return lines.join("");
    };
    chart.setOption({
      animation: false,
      textStyle: { fontFamily: palette.fontFamily, color: palette.muted },
      aria: {
        enabled: true,
        description:
          (comparison
            ? "本地日K与国家队估算持仓比例同图双轴对照，左轴价格、右轴比例，共享日期与缩放；缺失数据不补零。"
            : (indexPoints ? "指数原始日K和成交量。" : "基金原始日K和成交量。") + "上涨红色，下跌绿色；均线按源收盘价计算，复权口径未确认；悬停查看同日数值。") +
          "仅供研究，不构成投资建议。",
      },
      tooltip: {
        trigger: "axis",
        axisPointer: {
          type: "cross",
          label: { backgroundColor: palette.border, color: palette.ink },
        },
        backgroundColor: palette.surface,
        borderColor: palette.border,
        textStyle: {
          color: palette.ink,
          fontFamily: palette.fontFamily,
          fontSize: 11,
        },
        extraCssText: "max-width: 380px; white-space: normal;",
        formatter: tooltip,
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: comparison
        ? [{ left: 64, right: 96, top: 24, bottom: 64 }]
        : [
            { left: 64, right: 96, top: 20, height: "62%" },
            { left: 64, right: 96, top: "74%", height: "16%" },
          ],
      xAxis: (comparison ? [0] : [0, 1]).map((index) => ({
        type: "category",
        gridIndex: index,
        data: dates,
        axisLine: { lineStyle: { color: palette.border } },
        axisTick: { show: false },
        axisLabel: {
          show: comparison || index === 1,
          color: palette.muted,
          fontFamily: palette.fontFamily,
          fontSize: 10,
        },
        boundaryGap: true,
      })),
      yAxis: [
        {
          scale: true,
          name: indexPoints ? "指数点位" : "价格（元）",
          nameTextStyle: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
          },
          axisLabel: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
            formatter: (value: number) => value.toFixed(3),
          },
          splitLine: { lineStyle: { color: palette.border, opacity: 0.45 } },
        },
        {
          scale: !comparison,
          gridIndex: comparison ? 0 : 1,
          position: comparison ? "right" : "left",
          name: comparison ? "估算持仓比例（%）" : "成交量（源单位）",
          min: 0,
          max: comparison ? 100 : undefined,
          axisLabel: {
            color: comparison ? palette.chart2 : palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
            formatter: comparison
              ? "{value}%"
              : (value: number) => formatCompact(value),
          },
          nameTextStyle: {
            color: comparison ? palette.chart2 : palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
          },
          splitNumber: comparison ? 5 : 2,
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: comparison ? [0] : [0, 1] },
        {
          type: "slider",
          xAxisIndex: comparison ? [0] : [0, 1],
          bottom: 4,
          height: 16,
          borderColor: palette.border,
          textStyle: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
          },
          fillerColor: palette.primarySoft,
        },
      ],
      series: [
        {
          type: "candlestick",
          markPoint: { symbolSize: 30, data: trades.map((trade) => ({
            name: trade.side === "buy" ? "实际买入（委托日）" : "实际卖出（委托日）",
            coord: [trade.trade_date, Number(trade.price)], value: trade.side === "buy" ? "买" : "卖",
            itemStyle: { color: trade.side === "buy" ? palette.up : palette.down },
            label: { color: palette.surface, fontSize: 10 },
          })) },
          name: "日K · 开/收/低/高",
          data: dates.map((day) => {
            const r = candleByDate.get(day);
            return r ? [r.open, r.close, r.low, r.high] : [null, null, null, null];
          }),
          itemStyle: {
            color: palette.up,
            color0: palette.down,
            borderColor: palette.up,
            borderColor0: palette.down,
          },
        },
        ...maSeries.map(({ window, data }) => ({
          type: "line" as const,
          name: `MA${window}`,
          data,
          showSymbol: false,
          symbol: "none",
          connectNulls: false,
          z: 3,
          lineStyle: { width: MA_LINE_WIDTH[window], color: palette.ma[window] },
          itemStyle: { color: palette.ma[window] },
          ...(window === 10 || window === 30
            ? {
                endLabel: {
                  show: true,
                  color: palette.ma[window],
                  fontSize: 9,
                  fontFamily: palette.fontFamily,
                  formatter: (params: { value?: unknown }) => {
                    const value = Number(params.value);
                    return Number.isFinite(value)
                      ? `MA${window} ${formatPrice(value)}`
                      : "";
                  },
                },
              }
            : {}),
        })),
        comparison
          ? {
              type: "line",
              name: "国家队估算持仓比例（%）",
              xAxisIndex: 0,
              z: 5,
              yAxisIndex: 1,
              data: dates.map((day) => holdingByDate.get(day) ?? null),
              showSymbol: false,
              symbol: "none",
              connectNulls: false,
              itemStyle: { color: palette.chart2 },
              lineStyle: { width: 2, color: palette.chart2 },
            }
          : {
              type: "bar",
              name: "成交量",
              xAxisIndex: 1,
              yAxisIndex: 1,
              barWidth: "70%",
              data: rows.map((r) => ({
                value: r.volume,
                itemStyle: {
                  color: r.close >= r.open ? palette.up : palette.down,
                  opacity: 0.85,
                },
              })),
            },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [rows, theme, holdings, indexPoints, trades]);
  return (
    <div
      className={`kline ${holdings ? "holdings-comparison-chart" : ""}`}
      ref={element}
      role="img"
      aria-label={
        holdings
          ? "基金日K与国家队估算持仓比例同图双轴对照，共享日期与缩放，缺失不补零"
          : `${indexPoints ? "指数" : "基金"}日K、MA5至MA60均线与成交量，可滚轮缩放，悬停查看同日数值`
      }
    />
  );
}
