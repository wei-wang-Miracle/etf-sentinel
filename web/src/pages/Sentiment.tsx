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
type Daily = {
  trade_date: string;
  fear_greed_score: number;
  close_price: number | null;
  collected_at: string;
};
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
function Trend({ rows, theme }: { rows: Daily[]; theme: string }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current);
    const color = (name: string) =>
      getComputedStyle(document.documentElement)
        .getPropertyValue(`--color-${name}`)
        .trim();
    chart.setOption({
      animation: false,
      aria: { enabled: true },
      textStyle: { color: color("ink-muted"), fontFamily: "monospace" },
      tooltip: {
        trigger: "axis",
        backgroundColor: color("surface-elevated"),
        textStyle: { color: color("ink") },
      },
      grid: { left: 55, right: 65, top: 45, bottom: 65 },
      xAxis: { type: "category", data: rows.map((r) => r.trade_date) },
      yAxis: [
        {
          type: "value",
          name: "恐贪分数",
          min: 0,
          max: 100,
          interval: 20,
          nameTextStyle: { color: color("sentiment-fear") },
          axisLabel: { color: color("ink-muted") },
          splitLine: { lineStyle: { color: color("border") } },
        },
        {
          type: "value",
          name: "指数点位",
          scale: true,
          nameTextStyle: { color: color("chart-2") },
          axisLabel: { color: color("chart-2") },
          splitLine: { show: false },
        },
      ],
      visualMap: {
        type: "continuous",
        show: false,
        min: 0,
        max: 100,
        seriesIndex: 0,
        dimension: 1,
        inRange: {
          color: [
            color("sentiment-fear"),
            color("chart-6"),
            color("sentiment-greed"),
          ],
        },
      },
      dataZoom: [
        { type: "inside" },
        {
          type: "slider",
          height: 18,
          bottom: 8,
          borderColor: color("border"),
          textStyle: { color: color("ink-muted") },
          fillerColor: color("primary-soft"),
        },
      ],
      series: [
        {
          type: "line",
          name: "恐贪分数",
          yAxisIndex: 0,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 2.5 },
          encode: { x: 0, y: 1 },
          data: rows.map((r) => [r.trade_date, r.fear_greed_score]),
        },
        {
          type: "line",
          name: "指数点位",
          yAxisIndex: 1,
          showSymbol: false,
          connectNulls: false,
          itemStyle: { color: color("chart-2") },
          lineStyle: { color: color("chart-2"), width: 1.8, type: "dashed" },
          encode: { x: 0, y: 1 },
          data: rows.map((r) => [r.trade_date, r.close_price]),
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
              <Trend rows={rows} theme={theme} />
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
