import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { readChartPalette } from "../lib/chart";
import type { Candle } from "../lib/api";

echarts.use([
  AriaComponent,
  BarChart,
  CanvasRenderer,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  LineChart,
  TooltipComponent,
]);

export type EtfFlowPoint = {
  trade_date: string;
  unit_shares_100m: number | null;
  aum_100m: number | null;
  net_share_flow_7d_100m: number | null;
  net_share_flow_30d_100m: number | null;
  discount_premium_pct: number | null;
};

export default function EtfFlowChart({ rows, candles, theme }: { rows: EtfFlowPoint[]; candles: Candle[]; theme: string }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = element.current;
    return () => {
      if (node) echarts.getInstanceByDom(node)?.dispose();
    };
  }, []);
  useEffect(() => {
    if (!element.current || !rows.length) return;
    const chart = echarts.getInstanceByDom(element.current) ?? echarts.init(element.current);
    const p = readChartPalette();
    const dates = [...new Set([...rows.map((row) => row.trade_date), ...candles.map((row) => row.date)])].sort();
    const flowByDate = new Map(rows.map((row) => [row.trade_date, row]));
    const closeByDate = new Map(candles.map((row) => [row.date, row.close]));
    const compact = (value: unknown) => value == null ? "—" : Number(value).toFixed(2);
    chart.setOption({
      animation: false,
      textStyle: { color: p.muted, fontFamily: p.fontFamily },
      aria: {
        enabled: true,
        description: "ETF收盘价与近7日份额变动、收盘折溢价率的本地已采集截面，缺失值不补零，仅供研究观察。",
      },
      legend: {
        top: 4,
        textStyle: { color: p.muted },
        data: ["收盘价", "近7日份额变动", "折溢价率"],
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: p.surface,
        borderColor: p.border,
        textStyle: { color: p.ink },
        valueFormatter: compact,
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: element.current.clientWidth < 500 ? 44 : 68, right: element.current.clientWidth < 500 ? 44 : 68, top: 52, height: "34%" },
        { left: element.current.clientWidth < 500 ? 44 : 68, right: element.current.clientWidth < 500 ? 44 : 68, top: "56%", height: "24%" },
      ],
      xAxis: [0, 1].map((gridIndex) => ({
        type: "category",
        gridIndex,
        data: dates,
        boundaryGap: gridIndex === 1,
        axisLine: { lineStyle: { color: p.border } },
        axisTick: { show: false },
        axisLabel: { show: gridIndex === 1, color: p.muted },
      })),
      yAxis: [
        {
          type: "value",
          scale: true,
          name: "收盘价（元）",
          axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
        {
          type: "value",
          scale: true,
          name: "近7日变动（亿份）",
          position: "right",
          axisLabel: { color: p.muted },
          splitLine: { show: false },
        },
        {
          type: "value",
          gridIndex: 1,
          scale: true,
          name: "折溢价（%）",
          axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1] },
        { type: "slider", xAxisIndex: [0, 1], bottom: 3, height: 16, borderColor: p.border, fillerColor: p.primarySoft },
      ],
      series: [
        { name: "收盘价", type: "line", data: dates.map((day) => closeByDate.get(day) ?? null), showSymbol: false, connectNulls: false, itemStyle: { color: p.chart1 }, lineStyle: { width: 1.7 } },
        { name: "近7日份额变动", type: "bar", yAxisIndex: 1, data: dates.map((day) => flowByDate.get(day)?.net_share_flow_7d_100m ?? null), itemStyle: { color: p.chart6 } },
        { name: "折溢价率", type: "line", xAxisIndex: 1, yAxisIndex: 2, data: dates.map((day) => flowByDate.get(day)?.discount_premium_pct ?? null), showSymbol: false, connectNulls: false, itemStyle: { color: p.chart3 }, lineStyle: { width: 1.3 } },
      ],
    }, { notMerge: true });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => observer.disconnect();
  }, [rows, candles, theme]);
  return <div className="kline" ref={element} role="img" aria-label="ETF收盘价、份额变动和折溢价图" />;
}
