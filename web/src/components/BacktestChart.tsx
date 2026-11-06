import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  MarkLineComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { Result, Trade } from "../lib/backtests";
import {
  aggregateTradeMarkers,
  escapeHtml,
  formatPrice,
  readChartPalette,
} from "../lib/chart";
echarts.use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  LegendComponent,
  MarkLineComponent,
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
    const palette = readChartPalette();
    const { strategy, benchmark } = run.result;
    const dates = strategy.daily.map((r) => r.trade_date);
    const accounts = new Map(strategy.daily.map((r) => [r.trade_date, r]));
    const benchmarkAccounts = new Map(
      benchmark.daily.map((r) => [r.trade_date, r]),
    );
    const tradesByDate = new Map<string, Trade[]>();
    strategy.trades.forEach((trade) => {
      const rows = tradesByDate.get(trade.trade_date) ?? [];
      rows.push(trade);
      tradesByDate.set(trade.trade_date, rows);
    });
    const markers = aggregateTradeMarkers(strategy.trades, 20);
    const markerLabel = (marker: (typeof markers)[number]) =>
      `${marker.side === "buy" ? "买" : "卖"}${marker.count > 1 ? `×${marker.count}` : ""} ${formatPrice(marker.price)}`;
    const markerSeries = [
      { side: "buy", name: "买入", color: palette.up, rotate: 0 },
      { side: "sell", name: "卖出", color: palette.down, rotate: 180 },
    ].map((style) => ({
      name: style.name,
      type: "scatter" as const,
      symbol: "triangle",
      symbolRotate: style.rotate,
      symbolSize: 11,
      z: 10,
      itemStyle: {
        color: style.color,
        borderColor: palette.surface,
        borderWidth: 1,
      },
      label: {
        show: true,
        position: style.side === "buy" ? "bottom" : "top",
        distance: 6,
        formatter: (params: { data?: { label?: string } }) =>
          params.data?.label ?? "",
        color: palette.ink,
        backgroundColor: palette.surface,
        borderColor: style.color,
        borderWidth: 0.8,
        borderRadius: 3,
        padding: [2, 4],
        fontSize: 8,
        fontFamily: palette.fontFamily,
      },
      labelLayout: { hideOverlap: true },
      data: markers
        .filter((marker) => marker.side === style.side)
        .flatMap((marker) => {
          const account = accounts.get(marker.trade_date);
          return account
            ? [
                {
                  value: [marker.trade_date, account.nav],
                  label: markerLabel(marker),
                  tradeIndex: marker.tradeIndex,
                  side: marker.side,
                },
              ]
            : [];
        }),
    }));
    const tooltip = (raw: unknown) => {
      const list = raw as Array<{ axisValue?: string }>;
      const day = list[0]?.axisValue ?? "";
      const account = accounts.get(day);
      const benchmarkAccount = benchmarkAccounts.get(day);
      const lines = [
        `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(day)}</div>`,
      ];
      if (account) {
        lines.push(
          `<div>策略净值 <b>${account.nav.toFixed(4)}</b>　回撤 ${(account.drawdown * 100).toFixed(2)}%　仓位 ${(account.position_weight * 100).toFixed(0)}%</div>`,
        );
      }
      if (benchmarkAccount) {
        lines.push(
          `<div style="color:${palette.chart6}">买入持有净值 ${benchmarkAccount.nav.toFixed(4)}　回撤 ${(benchmarkAccount.drawdown * 100).toFixed(2)}%</div>`,
        );
      }
      (tradesByDate.get(day) ?? []).forEach((trade) => {
        lines.push(
          `<div style="margin-top:4px;color:${trade.side === "buy" ? palette.up : palette.down}">` +
            `${trade.side === "buy" ? "买入" : "卖出"} ${Number(trade.quantity).toLocaleString("zh-CN")} 份 @ ${formatPrice(Number(trade.price))} 元` +
            `</div>`,
          `<div style="color:${palette.muted}">信号 ${escapeHtml(trade.signal_date ?? "—")} → 执行 ${escapeHtml(trade.trade_date)}</div>`,
          `<div>${escapeHtml(trade.reason)}</div>`,
        );
      });
      return lines.join("");
    };
    chart.setOption({
      animation: false,
      textStyle: { color: palette.muted, fontFamily: palette.fontFamily },
      aria: {
        enabled: true,
        description:
          "策略与买入持有净值、各自回撤和策略实际仓位。买卖标记落在执行交易日，同日同向已合并，最多二十个；点击查看成交原因。仅供研究，不构成投资建议。",
      },
      legend: {
        top: 8,
        textStyle: {
          color: palette.muted,
          fontFamily: palette.fontFamily,
          fontSize: 11,
        },
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
        axisPointer: {
          type: "line",
          label: { backgroundColor: palette.border, color: palette.ink },
        },
        backgroundColor: palette.surface,
        borderColor: palette.border,
        textStyle: {
          color: palette.ink,
          fontFamily: palette.fontFamily,
          fontSize: 11,
        },
        extraCssText: "max-width: 420px; white-space: normal;",
        formatter: tooltip,
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: 72, right: 42, top: 56, height: "50%" },
        { left: 72, right: 42, top: "62%", height: "11%" },
        { left: 72, right: 42, top: "80%", height: "7%" },
      ],
      xAxis: [0, 1, 2].map((index) => ({
        type: "category",
        gridIndex: index,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: palette.border } },
        axisTick: { show: false },
        axisLabel: {
          show: index === 2,
          color: palette.muted,
          fontFamily: palette.fontFamily,
          fontSize: 10,
        },
      })),
      yAxis: [
        {
          name: "账户净值",
          scale: true,
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
          splitLine: { lineStyle: { color: palette.border, opacity: 0.5 } },
        },
        {
          name: "回撤（%）",
          gridIndex: 1,
          max: 0,
          splitNumber: 2,
          nameTextStyle: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
          },
          axisLabel: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
            formatter: "{value}%",
          },
          splitLine: { lineStyle: { color: palette.border, opacity: 0.5 } },
        },
        {
          name: "仓位（%）",
          gridIndex: 2,
          min: 0,
          max: 100,
          splitNumber: 1,
          nameTextStyle: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
          },
          axisLabel: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 10,
            formatter: "{value}%",
          },
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
          name: "策略净值",
          type: "line",
          data: strategy.daily.map((r) => r.nav),
          showSymbol: false,
          symbol: "none",
          lineStyle: { width: 2, color: palette.chart1 },
          itemStyle: { color: palette.chart1 },
          valueFormatter: (value: number) => value.toFixed(4),
          markLine: {
            silent: true,
            symbol: "none",
            label: {
              show: false,
            },
            lineStyle: {
              color: palette.muted,
              type: "dashed",
              width: 0.8,
              opacity: 0.65,
            },
            data: [{ yAxis: 1 }],
          },
        },
        {
          name: "买入持有",
          type: "line",
          data: benchmark.daily.map((r) => r.nav),
          showSymbol: false,
          symbol: "none",
          lineStyle: { width: 1.5, type: "dashed", color: palette.chart6 },
          itemStyle: { color: palette.chart6 },
          valueFormatter: (value: number) => value.toFixed(4),
        },
        ...[
          {
            key: "strategy" as const,
            name: "策略回撤",
            color: palette.chart1,
            type: "solid" as const,
          },
          {
            key: "benchmark" as const,
            name: "基准回撤",
            color: palette.chart6,
            type: "dashed" as const,
          },
        ].map((style) => ({
          name: style.name,
          type: "line" as const,
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: run.result[style.key].daily.map((r) =>
            Number((r.drawdown * 100).toFixed(3)),
          ),
          showSymbol: false,
          symbol: "none",
          lineStyle: { width: 1.2, type: style.type, color: style.color },
          itemStyle: { color: style.color },
          areaStyle: { opacity: 0.08 },
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
          symbol: "none",
          lineStyle: { width: 1.2, color: palette.chart2 },
          itemStyle: { color: palette.chart2 },
          areaStyle: { opacity: 0.15 },
        },
        ...markerSeries,
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
      aria-label="策略净值、基准净值、回撤及仓位联动图，买卖标记落在执行日，点击查看成交"
    />
  );
}
