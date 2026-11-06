import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { CandlestickChart, BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
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
  CanvasRenderer,
]);
import type { Candle } from "../lib/api";

export default function KLine({
  rows,
  theme,
  holdings,
}: {
  rows: Candle[];
  theme: string;
  holdings?: { trade_date: string; estimated_holding_pct: number | null }[];
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || (!rows.length && !holdings?.length)) return;
    const chart = echarts.init(element.current);
    const comparison = holdings !== undefined;
    const dates = comparison
      ? [...new Set([...rows.map((r) => r.date), ...holdings.map((r) => r.trade_date)])].sort()
      : rows.map((r) => r.date);
    const candleByDate = new Map(rows.map((r) => [r.date, r]));
    const holdingByDate = new Map(holdings?.map((r) => [r.trade_date, r.estimated_holding_pct]));
    const color = (name: string) =>
      getComputedStyle(document.documentElement)
        .getPropertyValue(`--color-${name}`)
        .trim();
    chart.setOption({
      animation: false,
      textStyle: { fontFamily: "monospace", color: color("ink-muted") },
      aria: {
        enabled: true,
        description:
          comparison
            ? "本地日K与国家队估算持仓比例同图双轴对照，左轴价格、右轴比例，共享日期与缩放；缺失数据不补零。"
            : "基金原始日K和成交量。上涨红色，下跌绿色；悬停查看同日数值。",
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: color("surface-elevated"),
        borderColor: color("border"),
        textStyle: { color: color("ink") },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: comparison
        ? [{ left: 60, right: 68, top: 40, bottom: 64 }]
        : [
            { left: 60, right: 30, top: 30, height: "58%" },
            { left: 60, right: 30, top: "73%", height: "15%" },
          ],
      xAxis: (comparison ? [0] : [0, 1]).map((index) => ({
        type: "category",
        gridIndex: index,
        data: dates,
        axisLine: { lineStyle: { color: color("border") } },
        axisLabel: { color: color("ink-muted"), show: comparison || index === 1 },
        boundaryGap: true,
      })),
      yAxis: [
        {
          scale: true,
          name: "价格（元）",
          splitLine: { lineStyle: { color: color("border"), opacity: 0.4 } },
        },
        {
          scale: true,
          gridIndex: comparison ? 0 : 1,
          position: comparison ? "right" : "left",
          name: comparison ? "估算持仓比例（%）" : "成交量（源单位）",
          ...(comparison ? { min: 0, max: 100, axisLabel: { formatter: "{value}%" }, nameTextStyle: { color: color("chart-2") } } : {}),
          splitNumber: 2,
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
          borderColor: color("border"),
          textStyle: { color: color("ink-muted") },
          fillerColor: color("primary-soft"),
        },
      ],
      series: [
        {
          type: "candlestick",
          name: "日K · 开/收/低/高",
          data: dates.map((day) => {
            const r = candleByDate.get(day);
            return r ? [r.open, r.close, r.low, r.high] : [null, null, null, null];
          }),
          itemStyle: {
            color: color("market-up"),
            color0: color("market-down"),
            borderColor: color("market-up"),
            borderColor0: color("market-down"),
          },
        },
        comparison ? {
          type: "line",
          name: "国家队估算持仓比例（%）",
          xAxisIndex: 0,
          z: 5,
          yAxisIndex: 1,
          data: dates.map((day) => holdingByDate.get(day) ?? null),
          showSymbol: false,
          connectNulls: false,
          itemStyle: { color: color("chart-2") },
          lineStyle: { width: 2, color: color("chart-2") },
        } : {
          type: "bar",
          name: "成交量",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: rows.map((r) => ({
            value: r.volume,
            itemStyle: {
              color: color(r.close >= r.open ? "market-up" : "market-down"),
              opacity: 0.4,
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
  }, [rows, theme, holdings]);
  return (
    <div
      className={`kline ${holdings ? "holdings-comparison-chart" : ""}`}
      ref={element}
      role="img"
      aria-label={holdings ? "基金日K与国家队估算持仓比例同图双轴对照，共享日期与缩放，缺失不补零" : "基金日K与成交量，可滚轮缩放，悬停查看同日数值"}
    />
  );
}
