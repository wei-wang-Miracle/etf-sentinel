import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  VisualMapContinuousComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { api, stamp } from "../lib/api";
import ChartCaption from "../components/ChartCaption";
import { escapeHtml, chartStamp, readChartPalette } from "../lib/chart";

echarts.use([
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AriaComponent,
  VisualMapContinuousComponent,
  CanvasRenderer,
]);
type Category = {
  category_key: string;
  category_name: string;
  index_name: string | null;
  count: number;
  first_date: string | null;
  last_date: string | null;
  fear_greed_score: number | null;
  close_price: number | null;
  source_label: string | null;
  collected_at: string | null;
  source: string;
};
export type SentimentDaily = {
  trade_date: string;
  fear_greed_score: number;
  close_price: number | null;
  collected_at: string;
};
export type MarketRegimePoint = {
  trade_date: string;
  factor_name: string;
  raw_value: number;
  source_pct_year: number | null;
  source_pct_all: number | null;
  collected_at: string;
};
export type MarketSentimentSeries = {
  fear_greed: { trade_date: string; fear_greed_score: number; source_label: string | null; collected_at: string }[];
  regime_factors: Record<string, MarketRegimePoint[]>;
};
export type MarketSentimentOverview = {
  latest: { trade_date: string | null; fear_greed_score: number | null; source_label: string | null; changes: Record<string, number | null> };
  coverage: { first_source_date: string | null; last_source_date: string | null; count: number };
  regime_factors: Record<string, { factor_name: string | null; raw_value: number | null; trade_date: string | null; first_source_date: string | null; last_source_date: string | null; count: number; source_pct_year: number | null; source_pct_all: number | null }>;
  source: string;
};
type Daily = SentimentDaily;
const today = () =>
  new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
function yearsAgo(years: number) {
  const day = new Date();
  day.setFullYear(day.getFullYear() - years);
  return day.toLocaleDateString("sv-SE");
}
function sentimentTone(label: string | null) {
  if (label?.includes("恐惧")) return "fear";
  if (label?.includes("贪婪")) return "greed";
  return "neutral";
}
export function SentimentTrend({ rows, theme }: { rows: Daily[]; theme: string }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const palette = readChartPalette();
    const byDate = new Map(rows.map((row) => [row.trade_date, row]));
    const tooltip = (raw: unknown) => {
      const list = raw as Array<{ axisValue?: string }>;
      const day = list[0]?.axisValue ?? "";
      const row = byDate.get(day);
      if (!row) return escapeHtml(day);
      return [
        `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(day)}</div>`,
        `<div>恐贪分数 <span style="color:${palette.fear}">${row.fear_greed_score.toFixed(2)}</span></div>`,
        `<div>指数点位 <span style="color:${palette.chart2}">${row.close_price == null ? "—" : row.close_price.toFixed(2)}</span></div>`,
      ].join("");
    };
    chart.setOption({
      animation: false,
      aria: {
        enabled: true,
        description:
          "恐贪分数与指数点位双轴历史图，左轴分数0至100，右轴指数点位，共享日期和缩放；两端数字为当前值，分数连续着色不代表源阈值。仅供研究，不构成建议。",
      },
      textStyle: { color: palette.muted, fontFamily: palette.fontFamily },
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
          fontSize: 12,
        },
        formatter: tooltip,
      },
      grid: { left: element.current.clientWidth < 500 ? 40 : 55, right: element.current.clientWidth < 500 ? 60 : 112, top: 32, bottom: 65 },
      xAxis: {
        type: "category",
        data: rows.map((r) => r.trade_date),
        axisLine: { lineStyle: { color: palette.border } },
        axisTick: { show: false },
        axisLabel: {
          color: palette.muted,
          fontFamily: palette.fontFamily,
          fontSize: 12,
        },
      },
      yAxis: [
        {
          type: "value",
          name: "恐贪分数",
          min: 0,
          max: 100,
          interval: 20,
          nameTextStyle: {
            color: palette.fear,
            fontFamily: palette.fontFamily,
            fontSize: 12,
          },
          axisLabel: {
            color: palette.muted,
            fontFamily: palette.fontFamily,
            fontSize: 12,
          },
          splitLine: { lineStyle: { color: palette.border, opacity: 0.45 } },
        },
        {
          type: "value",
          name: "指数点位",
          scale: true,
          nameTextStyle: {
            color: palette.chart2,
            fontFamily: palette.fontFamily,
            fontSize: 12,
          },
          axisLabel: {
            color: palette.chart2,
            fontFamily: palette.fontFamily,
            fontSize: 12,
            formatter: (value: number) => value.toFixed(0),
          },
          splitLine: { show: false },
        },
      ],
      visualMap: {
        type: "continuous",
        show: false,
        min: 0,
        max: 100,
        seriesIndex: 0,
        dimension: 0,
        inRange: {
          color: [palette.fear, palette.chart6, palette.greed],
        },
      },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 18,
          bottom: 8,
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
          type: "line",
          name: "恐贪分数",
          yAxisIndex: 0,
          showSymbol: false,
          symbol: "none",
          connectNulls: false,
          lineStyle: { width: 2.5 },
          data: rows.map((r) => r.fear_greed_score),
        },
        {
          type: "line",
          name: "指数点位",
          yAxisIndex: 1,
          showSymbol: false,
          symbol: "none",
          connectNulls: false,
          itemStyle: { color: palette.chart2 },
          lineStyle: { color: palette.chart2, width: 1.8, type: "dashed" },
          data: rows.map((r) => r.close_price),
          endLabel: {
            show: true,
            color: palette.chart2,
            fontSize: 12,
            fontFamily: palette.fontFamily,
            formatter: (params: { value?: unknown }) => {
              const value = Number(params.value);
              return Number.isFinite(value)
                ? `指数 ${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`
                : "";
            },
          },
        },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [rows, theme]);
  return (
    <div
      ref={element}
      className="sentiment-chart"
      role="img"
      aria-label="恐贪分数与指数点位双轴历史图，左轴分数0至100，右轴指数点位，共享日期和缩放"
    />
  );
}

export function MarketSentimentTrend({
  rows,
  theme,
}: {
  rows: MarketSentimentSeries;
  theme: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const palette = readChartPalette();
    const scores = new Map(rows.fear_greed.map((item) => [item.trade_date, item]));
    const volatility = new Map((rows.regime_factors.volatility ?? []).map((item) => [item.trade_date, item]));
    const days = [...new Set([...scores.keys(), ...volatility.keys()])].sort();
    chart.setOption({
      animation: false,
      aria: { enabled: true, description: "全市场恐贪分数与50ETF期权波动率双轴历史图，缺失源日期不补零。" },
      textStyle: { color: palette.muted, fontFamily: palette.fontFamily },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", label: { backgroundColor: palette.border, color: palette.ink } },
        backgroundColor: palette.surface,
        borderColor: palette.border,
        textStyle: { color: palette.ink, fontFamily: palette.fontFamily, fontSize: 12 },
        formatter: (raw: unknown) => {
          const day = (raw as Array<{ axisValue?: string }>)[0]?.axisValue ?? "";
          const score = scores.get(day)?.fear_greed_score;
          const ivix = volatility.get(day)?.raw_value;
          return `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(day)}</div><div>全市场恐贪 ${score == null ? "—" : score.toFixed(2)}</div><div>50ETF波指 ${ivix == null ? "—" : ivix.toFixed(2)}</div>`;
        },
      },
      grid: { left: element.current.clientWidth < 500 ? 40 : 55, right: element.current.clientWidth < 500 ? 60 : 88, top: 32, bottom: 65 },
      xAxis: { type: "category", data: days, axisLine: { lineStyle: { color: palette.border } }, axisTick: { show: false }, axisLabel: { color: palette.muted, fontFamily: palette.fontFamily, fontSize: 12 } },
      yAxis: [
        { type: "value", name: "恐贪分数", min: 0, max: 100, interval: 20, nameTextStyle: { color: palette.fear, fontFamily: palette.fontFamily, fontSize: 12 }, axisLabel: { color: palette.muted, fontFamily: palette.fontFamily, fontSize: 12 }, splitLine: { lineStyle: { color: palette.border, opacity: 0.45 } } },
        { type: "value", name: "iVIX", scale: true, nameTextStyle: { color: palette.chart3, fontFamily: palette.fontFamily, fontSize: 12 }, axisLabel: { color: palette.chart3, fontFamily: palette.fontFamily, fontSize: 12 }, splitLine: { show: false } },
      ],
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8, borderColor: palette.border, textStyle: { color: palette.muted, fontFamily: palette.fontFamily }, fillerColor: palette.primarySoft }],
      series: [
        { type: "line", name: "全市场恐贪", yAxisIndex: 0, showSymbol: false, symbol: "none", connectNulls: false, lineStyle: { width: 2.5 }, data: days.map((day) => scores.get(day)?.fear_greed_score ?? null) },
        { type: "line", name: "50ETF波指", yAxisIndex: 1, showSymbol: false, symbol: "none", connectNulls: false, lineStyle: { color: palette.chart3, width: 1.8, type: "dashed" }, data: days.map((day) => volatility.get(day)?.raw_value ?? null) },
      ],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [rows, theme]);
  return <div ref={element} className="sentiment-chart" role="img" aria-label="全市场恐贪分数与50ETF期权波动率双轴历史图" />;
}

export default function Sentiment({
  theme,
  goJobs,
}: {
  theme: string;
  goJobs: () => void;
}) {
  const [categories, setCategories] = useState<Category[]>([]);
  const [key, setKey] = useState("");
  const [rows, setRows] = useState<Daily[]>([]);
  const [start, setStart] = useState(() => yearsAgo(1));
  const [end, setEnd] = useState(today);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [categoryLoading, setCategoryLoading] = useState(true);
  const [categoryError, setCategoryError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setCategoryError("");
    setCategoryLoading(true);
    api<Category[]>(
      "/sentiment/categories",
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        setCategories(data);
        setKey((current) => current || data[0]?.category_key || "");
        setCategoryLoading(false);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setCategoryError(e.message);
          setCategoryLoading(false);
        }
      });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (!key) return;
    const controller = new AbortController();
    setLoading(true);
    setRows([]);
    setError("");
    api<Daily[]>(
      `/sentiment/series/${encodeURIComponent(key)}?start=${start}&end=${end}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((data) => {
        setRows(data);
        setLoading(false);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [key, start, end, refresh]);
  const selected = categories.find((item) => item.category_key === key);
  return (
    <>
      <header className="page-header">
        <div>
          <h1>行业恐贪</h1>
          <p>恐贪分数 × 指数点位 · 日频观察</p>
        </div>
        <button onClick={goJobs}>
          采集与调度
        </button>
      </header>
      {(categoryError || error) && (
        <div className="alert" role="alert">
          {categoryError || error}
          <button onClick={() => setRefresh((value) => value + 1)}>重试</button>
        </div>
      )}
      <div className="sentiment-cards">
        {categories.map((item) => (
          <button
            key={item.category_key}
            className={`panel sentiment-card ${key === item.category_key ? "selected" : ""}`}
            data-sentiment={sentimentTone(item.source_label)}
            aria-pressed={key === item.category_key}
            onClick={() => setKey(item.category_key)}
          >
            <span>{item.category_name}</span>
            <strong className="mono">
              {item.fear_greed_score?.toFixed(2) ?? "—"}
            </strong>
            <span className="sentiment-label">
              {item.source_label ?? "源标签暂无匹配快照"}
            </span>
            <span className="muted mono">{item.last_date ?? "尚无数据"}</span>
          </button>
        ))}
      </div>
      {categoryLoading && !categories.length && (
        <div className="empty" role="status">
          正在读取类别概览…
        </div>
      )}
      {!categories.length && !categoryLoading && !categoryError && (
        <section className="panel empty">
          尚未采集行业恐贪。<button onClick={goJobs}>前往首次采集</button>
        </section>
      )}
      {selected && (
        <section className="panel research-chart-panel">
          <div className="panel-header">
            <div>
              <h2>{selected.category_name}</h2>
              <span className="muted">
                {selected.index_name || "关联指数待源提供"} · 本地{" "}
                {selected.count} 个数据日
              </span>
            </div>
            <div className="range-buttons">
              {[1, 3, 5].map((year) => (
                <button
                  key={year}
                  onClick={() => {
                    setStart(yearsAgo(year));
                    setEnd(today());
                  }}
                >
                  {year} 年
                </button>
              ))}
            </div>
          </div>
          <div className="date-controls research-dates">
            <label>
              起始日期{" "}
              <input
                aria-label="恐贪起始日期"
                type="date"
                value={start}
                max={end}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              截止日期{" "}
              <input
                aria-label="恐贪截止日期"
                type="date"
                value={end}
                min={start}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
          {loading ? (
            <div className="empty" role="status">
              正在读取历史序列…
            </div>
          ) : !rows.length ? (
            <div className="empty">所选范围暂无数据</div>
          ) : (
            <>
              <div className="chart-toolbar sentiment-chart-header">
                <div className="sentiment-legend">
                  <span>
                    <i className="score-swatch" aria-hidden="true" />
                    恐贪分数 · 左轴
                  </span>
                  <span>
                    <i className="index-swatch" aria-hidden="true" />
                    指数点位 · 右轴
                  </span>
                </div>
              </div>
              <div className="sentiment-scale">
                <span>0 · 恐惧端</span>
                <span className="score-scale" aria-hidden="true" />
                <span>100 · 贪婪端</span>
              </div>
              <ChartCaption
                title={`${selected.category_name} · 恐贪分数 / 指数点位`}
                meta={`${start} ~ ${end} · 左轴 0–100 / 右轴指数点位 · 来源：韭圈 · 生成：${chartStamp()}`}
                disclaimer="恐贪不是买卖信号；分数连续着色不代表源阈值。仅供研究。"
              />
              <SentimentTrend rows={rows} theme={theme} />
              <div className="panel-footer">
                两条曲线使用独立刻度；悬停对照同日数据，滚轮或底部滑块缩放。分数连续着色，不代表源情绪阈值；指数缺失不补零。
              </div>
            </>
          )}
          <div className="panel-footer">
            来源：韭圈 · 行业恐贪 · 本地覆盖 {selected.first_date ?? "—"} ～{" "}
            {selected.last_date ?? "—"} · 最近采集{" "}
            {stamp(selected.collected_at)}
            。恐贪不是买卖信号；数据日期保留源口径。
          </div>
        </section>
      )}
    </>
  );
}
