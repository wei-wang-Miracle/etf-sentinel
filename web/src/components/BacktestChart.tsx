import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { Result } from "../lib/backtests";
echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  AriaComponent,
  CanvasRenderer,
]);

export default function BacktestChart({
  run,
  theme,
  onTrade,
}: {
  run: Result;
  theme: string;
  onTrade: (index: number) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const color = (key: string) =>
      getComputedStyle(document.documentElement)
        .getPropertyValue(`--color-${key}`)
        .trim();
    const { strategy, benchmark } = run.result;
    const dates = strategy.daily.map((r) => r.trade_date);
    const accounts = new Map(strategy.daily.map((r) => [r.trade_date, r]));
    chart.setOption({
      animation: false,
      textStyle: { color: color("ink-muted"), fontFamily: "monospace" },
      aria: {
        enabled: true,
        description:
          "策略与买入持有净值、各自回撤和策略实际仓位。点击买卖标记可查看成交原因。",
      },
      legend: {
        top: 8,
        textStyle: { color: color("ink-muted") },
        data: [
          "策略净值",
          "买入持有",
          "策略回撤",
          "基准回撤",
          "实际仓位",
          "买入",
          "卖出",
        ],
      },
      tooltip: {
        trigger: "axis",
        backgroundColor: color("surface-elevated"),
        borderColor: color("border"),
        textStyle: { color: color("ink") },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: 68, right: 32, top: 64, height: "43%" },
        { left: 68, right: 32, top: "61%", height: "13%" },
        { left: 68, right: 32, top: "81%", height: "9%" },
      ],
      xAxis: [0, 1, 2].map((index) => ({
        type: "category",
        gridIndex: index,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: color("border") } },
        axisLabel: { show: index === 2, color: color("ink-muted") },
      })),
      yAxis: [
        {
          name: "账户净值",
          scale: true,
          splitLine: { lineStyle: { color: color("border"), opacity: 0.5 } },
        },
        {
          name: "回撤（%）",
          gridIndex: 1,
          max: 0,
          splitNumber: 2,
          splitLine: { lineStyle: { color: color("border"), opacity: 0.5 } },
        },
        {
          name: "仓位（%）",
          gridIndex: 2,
          min: 0,
          max: 100,
          splitNumber: 1,
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1, 2] },
        {
          type: "slider",
          xAxisIndex: [0, 1, 2],
          bottom: 0,
          height: 16,
          borderColor: color("border"),
          fillerColor: color("primary-soft"),
          textStyle: { color: color("ink-muted") },
        },
      ],
      series: [
        {
          name: "策略净值",
          type: "line",
          data: strategy.daily.map((r) => r.nav),
          showSymbol: false,
          lineStyle: { width: 2 },
          itemStyle: { color: color("chart-1") },
          valueFormatter: (v: number) => v.toFixed(4),
        },
        {
          name: "买入持有",
          type: "line",
          data: benchmark.daily.map((r) => r.nav),
          showSymbol: false,
          lineStyle: { width: 1.5, type: "dashed" },
          itemStyle: { color: color("chart-6") },
          valueFormatter: (v: number) => v.toFixed(4),
        },
        ...[
          { key: "strategy" as const, name: "策略回撤", color: "chart-1" },
          { key: "benchmark" as const, name: "基准回撤", color: "chart-6" },
        ].map((s) => ({
          name: s.name,
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: run.result[s.key].daily.map((r) =>
            Number((r.drawdown * 100).toFixed(3)),
          ),
          showSymbol: false,
          areaStyle: { opacity: 0.08 },
          itemStyle: { color: color(s.color) },
        })),
        {
          name: "实际仓位",
          type: "line",
          xAxisIndex: 2,
          yAxisIndex: 2,
          step: "end",
          data: strategy.daily.map((r) =>
            Number((r.position_weight * 100).toFixed(2)),
          ),
          showSymbol: false,
          itemStyle: { color: color("chart-2") },
          areaStyle: { opacity: 0.15 },
        },
        ...[
          { side: "buy", name: "买入", color: "market-up", rotate: 0 },
          { side: "sell", name: "卖出", color: "market-down", rotate: 180 },
        ].map((s) => ({
          name: s.name,
          type: "scatter",
          symbol: "triangle",
          symbolRotate: s.rotate,
          symbolSize: 10,
          z: 10,
          itemStyle: { color: color(s.color) },
          data: strategy.trades
            .map((t, index) => ({
              value: [t.trade_date, accounts.get(t.trade_date)?.nav],
              tradeIndex: index,
              side: t.side,
            }))
            .filter((t) => t.side === s.side),
        })),
      ],
    });
    chart.on("click", (event) => {
      const item = event.data as { tradeIndex?: number };
      if (item?.tradeIndex != null) onTrade(item.tradeIndex);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [run, theme, onTrade]);
  return (
    <div
      ref={element}
      className="backtest-chart"
      role="img"
      aria-label="策略净值、基准净值、回撤及仓位联动图，点击买卖标记查看成交"
    />
  );
}
