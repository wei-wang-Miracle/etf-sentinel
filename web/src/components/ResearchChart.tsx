import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { readChartPalette } from "../lib/chart";

echarts.use([
  LineChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  AriaComponent,
  CanvasRenderer,
]);

export type LineSeries = { name: string; points: [string, number | null][] };
export default function ResearchChart({
  series,
  theme,
  unit,
  bounded = false,
}: {
  series: LineSeries[];
  theme: string;
  unit: string;
  bounded?: boolean;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = element.current;
    return () => {
      if (node) echarts.getInstanceByDom(node)?.dispose();
    };
  }, []);
  useEffect(() => {
    if (!element.current || !series.some((row) => row.points.length)) return;
    const chart = echarts.getInstanceByDom(element.current) ?? echarts.init(element.current);
    const p = readChartPalette();
    const chartColors = [p.chart1, p.chart2, p.chart3, p.chart4, p.chart5, p.chart6];
    const dates = [
      ...new Set(series.flatMap((row) => row.points.map(([day]) => day))),
    ].sort();
    chart.setOption({
      animation: false,
      color: chartColors,
      textStyle: { color: p.muted, fontFamily: p.fontFamily },
      aria: { enabled: true },
      legend: { type: "scroll", top: 0, textStyle: { color: p.ink } },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: p.surface,
        borderColor: p.border,
        textStyle: { color: p.ink },
        valueFormatter: (v: unknown) =>
          v == null ? "—" : Number(v).toFixed(2),
      },
      grid: { left: 65, right: 30, top: 55, bottom: 60 },
      xAxis: { type: "category", data: dates, axisLabel: { color: p.muted } },
      yAxis: {
        type: "value",
        name: unit,
        scale: !bounded,
        min: bounded ? 0 : undefined,
        max: bounded ? 100 : undefined,
        splitLine: { lineStyle: { color: p.border, opacity: 0.45 } },
      },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 5 }],
      series: series.map((row, index) => {
        const points = new Map(row.points);
        return {
          type: "line",
          name: row.name,
          itemStyle: { color: chartColors[index % chartColors.length] },
          data: dates.map((day) => points.get(day) ?? null),
          showSymbol: false,
          connectNulls: false,
        };
      }),
    }, { notMerge: true });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
    };
  }, [series, theme, unit, bounded]);
  const hasPoints = series.some((row) => row.points.length);
  function resetZoom() {
    if (!element.current) return;
    echarts.getInstanceByDom(element.current)?.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
  }
  return hasPoints ? (
    <><div
      className="kline"
      ref={element}
      role="img"
      aria-label={`${unit}时序对比，缺失不连线，支持缩放和悬停`}
    /><div className="chart-aux-bar"><button type="button" className="chart-reset-zoom" onClick={resetZoom}>重置缩放</button></div></>
  ) : (
    <div className="empty">所选对象在此区间无可绘制序列</div>
  );
}

export function ResearchHeatmap({
  data,
  theme,
  sentiment = false,
}: {
  data: { rows: string[]; columns: string[]; values: (number | null)[][] };
  theme: string;
  sentiment?: boolean;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = element.current;
    return () => {
      if (node) echarts.getInstanceByDom(node)?.dispose();
    };
  }, []);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.getInstanceByDom(element.current) ?? echarts.init(element.current);
    const p = readChartPalette();
    const points = data.values.flatMap((row, y) =>
      row.flatMap((value, x) => (value == null ? [] : [[x, y, value]])),
    );
    chart.setOption({
      animation: false,
      textStyle: { color: p.muted },
      tooltip: {
        position: "top",
        confine: true,
        backgroundColor: p.surface,
        borderColor: p.border,
        textStyle: { color: p.ink },
        formatter: (params: { value: number[] }) =>
          `${data.rows[params.value[1]]} · ${data.columns[params.value[0]]}：${params.value[2].toFixed(2)}`,
      },
      grid: { left: 105, right: 25, top: 15, bottom: 80 },
      xAxis: {
        type: "category",
        data: data.columns,
        axisLabel: { color: p.muted },
      },
      yAxis: {
        type: "category",
        data: data.rows,
        axisLabel: { color: p.muted },
      },
      visualMap: {
        min: 0,
        max: 100,
        calculable: true,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        inRange: {
          color: sentiment
            ? [p.fear, p.surface, p.greed]
            : [p.surface, p.chart1],
        },
        textStyle: { color: p.ink },
      },
      series: [{ type: "heatmap", data: points, progressive: 0 }],
      aria: { enabled: true },
    }, { notMerge: true });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
    };
  }, [data, theme, sentiment]);
  return (
    <div
      className="kline"
      ref={element}
      role="img"
      aria-label="同口径横截面热力图，空白格为缺失，不代表零"
    />
  );
}
