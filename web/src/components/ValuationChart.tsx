import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ChartReadout from "./ChartReadout";
import { readChartPalette } from "../lib/chart";
import type { ValuationPoint } from "../pages/IndexValuations";
import type { Candle } from "../lib/api";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  LegendComponent,
  CanvasRenderer,
]);

export default function ValuationChart({
  rows,
  candles,
  title,
  unit,
  theme,
}: {
  rows: ValuationPoint[];
  candles: Candle[];
  title: string;
  unit: string;
  theme: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current || !rows.length) return;
    const chart = echarts.init(element.current);
    const p = readChartPalette();
    const dates = [
      ...new Set([
        ...rows.map((r) => r.trade_date),
        ...candles.map((r) => r.date),
      ]),
    ].sort();
    const byDate = new Map(rows.map((r) => [r.trade_date, r]));
    const closes = new Map(candles.map((r) => [r.date, r.close]));
    chart.setOption({
      animation: false,
      textStyle: { color: p.muted, fontFamily: p.fontFamily },
      aria: {
        enabled: true,
        description:
          "估值与指数点位双轴对照，下方为截至当日的本地十年窗口分位；缺失不补零，仅供研究。",
      },
      legend: {
        top: 4,
        textStyle: { color: p.muted },
        data: [title, "指数收盘点位", "本地回看分位"],
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: p.surface,
        borderColor: p.border,
        textStyle: { color: p.ink },
        valueFormatter: (v: unknown) =>
          v == null ? "—" : Number(v).toFixed(2),
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: element.current.clientWidth < 500 ? 44 : 70, right: element.current.clientWidth < 500 ? 46 : 85, top: 50, height: "52%" },
        { left: element.current.clientWidth < 500 ? 44 : 70, right: element.current.clientWidth < 500 ? 46 : 85, top: "70%", height: "18%" },
      ],
      xAxis: [0, 1].map((i) => ({
        type: "category",
        gridIndex: i,
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: p.border } },
        axisLabel: { show: i === 1, color: p.muted },
        axisTick: { show: false },
      })),
      yAxis: [
        {
          type: "value",
          scale: true,
          name: `${title}（${unit}）`,
          axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
        {
          type: "value",
          scale: true,
          name: "指数点位",
          position: "right",
          axisLabel: { color: p.muted },
          splitLine: { show: false },
        },
        {
          type: "value",
          gridIndex: 1,
          min: 0,
          max: 100,
          name: "分位（%）",
          splitNumber: 2,
          axisLabel: { color: p.muted },
          splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
        },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1] },
        {
          type: "slider",
          xAxisIndex: [0, 1],
          bottom: 3,
          height: 16,
          borderColor: p.border,
          fillerColor: p.primarySoft,
        },
      ],
      series: [
        {
          name: title,
          type: "line",
          data: dates.map((d) =>
            byDate.get(d)?.value_status === "valid"
              ? byDate.get(d)?.value
              : null,
          ),
          showSymbol: false,
          connectNulls: false,
          itemStyle: { color: p.chart1 },
          lineStyle: { width: 1.6 },
        },
        {
          name: "指数收盘点位",
          type: "line",
          yAxisIndex: 1,
          data: dates.map((d) => closes.get(d) ?? null),
          showSymbol: false,
          connectNulls: false,
          itemStyle: { color: p.chart2 },
          lineStyle: { width: 1.1 },
        },
        {
          name: "本地回看分位",
          type: "line",
          xAxisIndex: 1,
          yAxisIndex: 2,
          data: dates.map((d) => byDate.get(d)?.local_percentile ?? null),
          showSymbol: false,
          connectNulls: false,
          itemStyle: { color: p.chart6 },
          lineStyle: { width: 1.3 },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [rows, candles, title, unit, theme]);
  return (
    <><div
      className="kline"
      ref={element}
      role="img"
      aria-label={`${title}、指数点位与本地回看分位，可缩放及悬停查看`}
    /><ChartReadout rows={rows.map(row => ({ date: row.trade_date, values: { [title]: row.value == null ? "—" : `${row.value} ${unit}`, "本地十年回看分位": row.local_percentile == null ? "—" : `${row.local_percentile}%`, "指数收盘点位": String(candles.find(item => item.date === row.trade_date)?.close ?? "—") } }))} /></>
  );
}
