import { useEffect, useRef, useState } from "react";
import ChartCaption from "../components/ChartCaption";
import { api } from "../lib/api";
import { dateAgo, metrics, number, useResearchQuery } from "../lib/research";
import ResearchChart, {
  ResearchHeatmap,
  type LineSeries,
} from "../components/ResearchChart";

type Item = {
  code: string;
  name: string;
  object_type: string;
  rank: number | null;
  status: string;
  latest: number | null;
  change: number | null;
  coverage_pct: number;
  as_of: string | null;
  source_label: string | null;
  max_drawdown?: number;
  volatility?: number;
  ma_state?: Record<string, string>;
  warning?: string;
  index_code?: string | null;
  index_name?: string | null;
  shared_index_codes?: string[];
};
type Result = {
  dimension: string;
  start: string;
  end: string;
  as_of: string;
  universe: { total: number; covered: number; holdings_as_of?: string | null; independent_sources?: number | null };
  meta: { unit: string; source: string; stale_rule: string };
  items: Item[];
  series: (LineSeries & { code: string; drawdowns: [string, number][] })[];
  warnings: string[];
  heatmap: {
    rows: string[];
    columns: string[];
    values: (number | null)[][];
  } | null;
};
const dimensions: Record<string, string> = {
  valuation: "ETF关联估值",
  sentiment: "市场情绪背景",
  holdings: "国家队资金",
  trend: "价格趋势",
  factors: "因子（后接）",
};
const reasons: Record<string, string> = {
  available: "可比较",
  stale: "评价日缺失／过期",
  missing: "暂无数据",
  missing_dates: "区间缺少交易日",
  invalid_price: "价格无效",
  split: "存在份额折算",
};

export default function Compare({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({
    dimension: "valuation",
    metric: "pe",
    start: dateAgo(300),
    end: dateAgo(1),
    codes: "",
    scope: "held",
  });
  const { start, end } = query;
  const scope = query.scope === "all" ? "all" : "held";
  const dimension = dimensions[query.dimension] ? query.dimension : "valuation";
  const metric = metrics[query.metric] ? query.metric : "pe";
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [ascending, setAscending] = useState(false);
  const [view, setView] = useState("series");
  const selections = useRef<Record<string, string>>({});
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError("");
    if (!start || !end || start > end) {
      setError("请选择有效日期区间");
      setLoading(false);
      return;
    }
    setLoading(true);
    const params = new URLSearchParams({ dimension, start, end, metric, scope });
    if (query.codes) params.set("codes", query.codes);
    api<Result>(
      `/research/compare?${params}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then(setResult)
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [dimension, metric, start, end, query.codes, scope, refresh]);
  const selected = query.codes
    ? query.codes.split(",")
    : (result?.series.map((row) => row.code) ?? []);
  const items = [...(result?.items ?? [])].sort((a, b) =>
    a.rank == null
      ? 1
      : b.rank == null
        ? -1
        : ascending
          ? a.latest! - b.latest!
          : b.latest! - a.latest!,
  );
  function switchDimension(value: string) {
    selections.current[dimension] = query.codes;
    update({ dimension: value, codes: selections.current[value] ?? "" });
    setView("series");
  }
  return (
    <>
      <header className="page-header">
        <div>
          <h1>横向对比</h1>
          <p>以ETF为研究主体，指数提供关联因子；市场情绪单独作为背景</p>
        </div>
      </header>
      <section className="panel research-chart-panel integrated-research">
        <div className="chart-toolbar">
          <div className="research-tabs" role="tablist" aria-label="比较维度">
            {Object.entries(dimensions).map(([key, name]) => (
              <button
                key={key}
                role="tab"
                aria-selected={dimension === key}
                onClick={() => switchDimension(key)}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="date-controls">
            {dimension !== "sentiment" && <label>
              ETF集合{" "}
              <select aria-label="ETF集合" value={scope} onChange={(e) => update({ scope: e.target.value, codes: "" })}>
                <option value="held">当前正持仓</option>
                <option value="all">全部配置</option>
              </select>
            </label>}
            <label>
              起始{" "}
              <input
                type="date"
                value={start}
                onChange={(e) => update({ start: e.target.value })}
              />
            </label>
            <label>
              截止{" "}
              <input
                type="date"
                value={end}
                onChange={(e) => update({ end: e.target.value })}
              />
            </label>
            {dimension === "valuation" && (
              <label>
                指标{" "}
                <select
                  value={metric}
                  onChange={(e) => update({ metric: e.target.value })}
                >
                  {Object.entries(metrics).map(([key, value]) => (
                    <option value={key} key={key}>
                      {value.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
        {(dimension !== query.dimension || metric !== query.metric) && (
          <p className="notice warning">无效维度或指标已回退为默认值。</p>
        )}
        {loading ? (
          <div className="empty" role="status">
            正在核对共同日期与覆盖…
          </div>
        ) : error ? (
          <div className="empty" role="alert">
            {error}{" "}
            <button onClick={() => setRefresh(refresh + 1)}>重试</button>
          </div>
        ) : (
          result && (
            <>
              <div className="quote-strip">
                <div>
                  <span>共同区间</span>
                  <strong>
                    {result.start} — {result.end}
                  </strong>
                </div>
                <div>
                  <span>{dimension === "sentiment" ? "可比较市场类别" : "可比较ETF"}</span>
                  <strong>
                    {result.universe.covered} / {result.universe.total}
                  </strong>
                </div>
                <div>
                  <span>统一单位</span>
                  <strong>{result.meta.unit}</strong>
                </div>
              </div>
              {dimension === "valuation" && <p className="muted">独立关联指数来源 {result.universe.independent_sources ?? 0} 个；ETF行数不代表独立信息数量。</p>}
              {dimension !== "sentiment" && <p className="muted">持仓快照：{result.universe.holdings_as_of ?? "尚未同步"}；快照日期不等于当前实时持仓。研究资金每只50,000元，实际持仓按同步记录。</p>}
              {result.items.length === 0 && dimension !== "factors" && <div className="empty">{scope === "held" && dimension !== "sentiment" ? "暂无当前正持仓ETF，请同步账户或选择全部配置。" : "当前范围暂无数据。"}</div>}
              {result.warnings.map((message) => (
                <p className="muted" key={message}>
                  {message}
                </p>
              ))}
              {items.length > 0 && (
                <>
                  <div className="research-selection">
                    {items.map((item) => (
                      <label key={item.code}>
                        <input
                          type="checkbox"
                          checked={selected.includes(item.code)}
                          disabled={
                            !selected.includes(item.code) &&
                            selected.length >= 6
                          }
                          onChange={(e) =>
                            update({
                              codes: e.target.checked
                                ? [...selected, item.code].join(",")
                                : selected
                                    .filter((code) => code !== item.code)
                                    .join(",") || "none",
                            })
                          }
                        />
                        {item.code} · {item.name}
                      </label>
                    ))}
                  </div>
                  <div className="chart-toolbar">
                    <button onClick={() => update({ codes: "" })}>
                      {dimension === "sentiment" ? "分数前六类别" : "数值前六ETF"}
                    </button>
                    <button
                      aria-pressed={view === "series"}
                      onClick={() => setView("series")}
                    >
                      时序
                    </button>
                    {dimension === "trend" && (
                      <button
                        aria-pressed={view === "drawdown"}
                        onClick={() => setView("drawdown")}
                      >
                        价格回撤
                      </button>
                    )}
                    {result.heatmap && (
                      <button
                        aria-pressed={view === "heatmap"}
                        onClick={() => setView("heatmap")}
                      >
                        热力图
                      </button>
                    )}
                  </div>
                  {view === "heatmap" && result.heatmap ? (
                    <ResearchHeatmap
                      data={result.heatmap}
                      theme={theme}
                      sentiment={dimension === "sentiment"}
                    />
                  ) : (
                    <ResearchChart
                      theme={theme}
                      unit={
                        view === "drawdown" ? "价格回撤（%）" : result.meta.unit
                      }
                      bounded={dimension !== "trend"}
                      series={result.series.map((row) => ({
                        name: row.name,
                        points:
                          view === "drawdown" ? row.drawdowns : row.points,
                      }))}
                    />
                  )}
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>{dimension === "sentiment" ? "类别分数顺序 / 市场背景" : "同值并列 / ETF"}</th>
                          <th
                            aria-sort={ascending ? "ascending" : "descending"}
                          >
                            <button onClick={() => setAscending(!ascending)}>
                              {dimension === "trend"
                                ? "价格变化（%）"
                                : "最新值"}{" "}
                              {ascending ? "↑" : "↓"}
                            </button>
                          </th>
                          <th>
                            区间变化
                            {dimension === "trend" ? "（%）" : "（分／百分点）"}
                          </th>
                          {dimension === "trend" && (
                            <>
                              <th>最大回撤 / 波动（%）</th>
                              <th>均线状态</th>
                            </>
                          )}
                          <th>覆盖 / 源日期</th>
                          <th>状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((item) => (
                          <tr key={item.code}>
                            <td>
                              <span className="mono">
                                {item.rank ?? "—"} ·{" "}
                              </span>
                              {item.object_type === "sentiment" ? (
                                item.name
                              ) : (
                                <a
                                  href={`?page=research&object=${item.object_type}:${item.code}&start=${start}&end=${end}`}
                                >
                                  {item.code} · {item.name}
                                </a>
                              )}
                              <small className="subtext">{item.code}</small>
                              {dimension === "valuation" && <small className="subtext">
                                {item.index_code ? `关联指数：${item.index_name ?? ""} ${item.index_code}` : "暂无关联指数"}
                                {(item.shared_index_codes?.length ?? 0) > 1 ? ` · 与${item.shared_index_codes!.filter((code) => code !== item.code).join("、")}共享来源` : ""}
                              </small>}
                            </td>
                            <td className="number">
                              {item.rank == null ? "—" : number(item.latest)}
                            </td>
                            <td className="number">{number(item.change)}</td>
                            {dimension === "trend" && (
                              <>
                                <td className="number">
                                  {number(item.max_drawdown)} /{" "}
                                  {number(item.volatility)}
                                </td>
                                <td>
                                  20日 {item.ma_state?.["20"] ?? "—"}
                                  <small className="subtext">
                                    60日 {item.ma_state?.["60"] ?? "—"}
                                  </small>
                                </td>
                              </>
                            )}
                            <td className="number">
                              {number(item.coverage_pct, 1)}%
                              <small className="subtext">
                                {item.as_of ?? "无日期"}
                              </small>
                            </td>
                            <td>
                              {reasons[item.status] ?? "不可比"}
                              <small className="subtext">
                                {item.source_label ??
                                  (dimension === "sentiment"
                                    ? "源标签暂无"
                                    : item.warning)}
                              </small>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              <ChartCaption
                title={`${dimensions[dimension]} · 日频 · ${result.meta.unit}`}
                meta={`${result.start} 至 ${result.end} · ${result.meta.source} · 查看时间 ${new Date().toLocaleString("zh-CN")}`}
              />
              <p className="muted">
                来源：{result.meta.source} · {result.meta.stale_rule} ·
                仅供研究，不构成投资建议。
              </p>
            </>
          )
        )}
      </section>
    </>
  );
}
