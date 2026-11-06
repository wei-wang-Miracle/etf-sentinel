import { useEffect, useState } from "react";
import { api, stamp, type Candle } from "../lib/api";
import { chartStamp } from "../lib/chart";
import ChartCaption from "../components/ChartCaption";
import KLine from "../components/KLine";
import ValuationChart from "../components/ValuationChart";

type Metric = {
  name: string;
  unit: string;
  value: number | null;
  value_status: string;
  trade_date: string | null;
  first_date: string | null;
  count: number;
  valid_count: number;
  local_percentile: number | null;
  source_percentile: number | null;
  collected_at: string | null;
};
type Index = {
  collection_warnings: string[];
  index_code: string;
  index_name: string;
  instrument_codes: string[];
  metrics: Record<string, Metric>;
  source_date: string | null;
  source_stale: boolean | null;
  source_insufficient: boolean | null;
  source_not_applicable: boolean | null;
  observed_at: string | null;
  candle_count: number;
  candle_first_date: string | null;
  candle_last_date: string | null;
};
type Overview = {
  indices: Index[];
  latest_run_status: string | null;
  latest_run_at: string | null;
};
export type ValuationPoint = {
  trade_date: string;
  value: number | null;
  value_status: string;
  local_percentile: number | null;
  collected_at: string;
};
type Series = { series: ValuationPoint[]; candles: Candle[] };
const today = () =>
  new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
const fmt = (v: number | null | undefined) =>
  v == null ? "—" : Number(v).toFixed(2);
const keys = ["pe", "pb", "xilv", "roe", "premium_diff"];

export default function IndexValuations({
  theme,
  goJobs,
}: {
  theme: string;
  goJobs: () => void;
}) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [code, setCode] = useState("000905.SH");
  const [fund, setFund] = useState("");
  const [metric, setMetric] = useState("pe");
  const [start, setStart] = useState("2016-01-01");
  const [end, setEnd] = useState(today);
  const [data, setData] = useState<Series | null>(null);
  const [loading, setLoading] = useState(true);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [error, setError] = useState("");
  const [directoryError, setDirectoryError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const c = new AbortController();
    setDirectoryLoading(true);
    setDirectoryError("");
    api<Overview>("/index-valuations", "GET", undefined, c.signal)
      .then(setOverview)
      .catch((e) => {
        if (!c.signal.aborted) setDirectoryError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setDirectoryLoading(false);
      });
    return () => c.abort();
  }, [refresh]);
  useEffect(() => {
    const c = new AbortController();
    setData(null);
    setError("");
    if (!start || !end || start > end) {
      setLoading(false);
      setError("请选择有效起止日期");
      return;
    }
    setLoading(true);
    api<Series>(
      `/index-valuations/series/${code}?metric=${metric}&start=${start}&end=${end}`,
      "GET",
      undefined,
      c.signal,
    )
      .then(setData)
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!c.signal.aborted) setLoading(false);
      });
    return () => c.abort();
  }, [code, metric, start, end, refresh]);
  const items = overview?.indices ?? [];
  const filtered = fund
    ? items.filter((i) => i.instrument_codes.includes(fund))
    : items;
  const selected = items.find((i) => i.index_code === code);
  const m = selected?.metrics[metric];
  const funds = items.flatMap((i) => i.instrument_codes).sort();
  const stale =
    m?.trade_date &&
    (Date.parse(today()) - Date.parse(m.trade_date)) / 86400000 > 7;
  function selectFund(value: string) {
    setFund(value);
    if (value) {
      const match = items.find((i) => i.instrument_codes.includes(value));
      if (match) setCode(match.index_code);
    }
  }
  return (
    <>
      <header className="page-header">
        <div>
          <h1>指数估值</h1>
          <p>当前ETF的关联指数 · 日频估值与指数走势对照</p>
        </div>
        <div className="range-buttons">
          <button onClick={() => setRefresh((n) => n + 1)}>刷新本地数据</button>
          <button onClick={goJobs}>采集与调度</button>
        </div>
      </header>
      {(directoryError || error) && (
        <div className="alert" role="alert">
          {directoryError || error}{" "}
          <button onClick={() => setRefresh((n) => n + 1)}>重试</button>
        </div>
      )}
      {directoryLoading && !items.length && (
        <div className="empty" role="status">
          正在读取指数目录…
        </div>
      )}
      {!directoryLoading && !directoryError && !items.length && (
        <div className="panel empty">
          尚无关联指数，请先升级数据库并运行指数估值采集。
          <button onClick={goJobs}>前往采集</button>
        </div>
      )}
      {selected && (
        <>
          <section className="panel" aria-label="关联指数概览">
            <div className="chart-toolbar">
              <span className="muted">
                {filtered.length}个关联指数 · {m?.name} · {m?.unit}
              </span>
              <div className="range-buttons">
                {filtered.map((item) => (
                  <button
                    key={item.index_code}
                    title={item.index_code}
                    aria-pressed={code === item.index_code}
                    className={code === item.index_code ? "active" : ""}
                    onClick={() => setCode(item.index_code)}
                  >
                    {item.index_name}{" "}
                    <span className="mono">
                      {item.metrics[metric].value_status === "valid"
                        ? fmt(item.metrics[metric].value)
                        : "—"}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </section>
          <section className="panel research-chart-panel">
            <div className="panel-header chart-heading">
              <div className="research-context">
                <h2>{selected.index_name}</h2>
                <label className="compact-selector">
                  关联ETF
                  <select
                    aria-label="关联ETF筛选"
                    value={fund}
                    onChange={(e) => selectFund(e.target.value)}
                  >
                    <option value="">全部当前标的</option>
                    {funds.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="compact-selector">
                  指数
                  <select
                    aria-label="研究指数"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  >
                    {filtered.map((i) => (
                      <option key={i.index_code} value={i.index_code}>
                        {i.index_code} · {i.index_name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="date-controls">
                <label>
                  起始{" "}
                  <input
                    aria-label="估值起始日期"
                    type="date"
                    value={start}
                    max={end}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </label>
                <label>
                  截止{" "}
                  <input
                    aria-label="估值截止日期"
                    type="date"
                    value={end}
                    min={start}
                    max={today()}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </label>
              </div>
            </div>
            <div className="quote-strip">
              {keys.map((k) => {
                const v = selected.metrics[k];
                return (
                  <div key={k}>
                    <span>
                      {v.name} · {v.unit}
                    </span>
                    <strong>
                      {v.value_status === "valid"
                        ? fmt(v.value)
                        : "不适用 / 缺失"}
                    </strong>
                    <span>源日 {v.trade_date ?? "尚未采集"}</span>
                  </div>
                );
              })}
            </div>
            <div className="chart-toolbar">
              <div className="range-buttons">
                {keys.map((k) => (
                  <button
                    key={k}
                    className={metric === k ? "active" : ""}
                    onClick={() => setMetric(k)}
                  >
                    {selected.metrics[k].name}
                  </button>
                ))}
              </div>
              <div className="range-buttons">
                {[3, 5, 10].map((y) => (
                  <button
                    key={y}
                    onClick={() => {
                      const d = new Date(`${today()}T00:00:00Z`);
                      d.setUTCFullYear(d.getUTCFullYear() - y);
                      setStart(d.toISOString().slice(0, 10));
                      setEnd(today());
                    }}
                  >
                    近{y}年
                  </button>
                ))}
                <button
                  onClick={() => {
                    setStart(m?.first_date ?? "2016-01-01");
                    setEnd(today());
                  }}
                >
                  全部
                </button>
              </div>
            </div>
            {(overview?.latest_run_status === "partial" ||
              overview?.latest_run_status === "failed" ||
              overview?.latest_run_status === "interrupted") && (
              <div className="notice warning">
                最近采集未全部成功，当前显示已保存历史；请查看采集记录。运行时间：
                {stamp(overview.latest_run_at)}
              </div>
            )}
            {selected.collection_warnings.map((warning, i) => (
              <div key={i} className="notice warning">
                {warning}
              </div>
            ))}
            {(stale || selected.source_stale) && (
              <div className="notice warning">
                估值来源已标过期或源日期距今超过七天，请检查更新。
              </div>
            )}
            {(selected.source_insufficient ||
              selected.source_not_applicable) && (
              <div className="notice warning">
                源标记历史不足或估值不适用，请结合各指标实际有效样本查看。
              </div>
            )}
            {m && (
              <div className="chart-toolbar">
                <span>
                  本地回看分位{" "}
                  <strong className="mono">{fmt(m.local_percentile)}%</strong>
                  {"　·　来源概览分位 "}
                  <span className="mono">{fmt(m.source_percentile)}%</span>
                </span>
                <span className="muted mono">
                  实际覆盖 {m.first_date ?? "—"} ～ {m.trade_date ?? "—"} ·{" "}
                  {m.valid_count} / {m.count} 个有效样本
                </span>
              </div>
            )}
            {loading ? (
              <div className="empty chart-empty" role="status">
                正在读取估值历史…
              </div>
            ) : error ? (
              <div className="empty">读取失败，请重试。</div>
            ) : !data?.series.length ? (
              <div className="empty chart-empty">
                所选区间暂无估值，请调整日期或运行采集任务。
              </div>
            ) : (
              m && (
                <>
                  <ChartCaption
                    title={`${code} · ${m.name} / 指数点位`}
                    meta={`${start} ~ ${end} · 日频 · 来源：韭圈估值 / ChatBI指数行情 · 生成：${chartStamp()}`}
                  />
                  <ValuationChart
                    rows={data.series}
                    candles={data.candles}
                    title={m.name}
                    unit={m.unit}
                    theme={theme}
                  />
                </>
              )
            )}
            <div className="panel-footer">
              本地回看分位：截至当日、最多往前10个日历年的有效样本，严格小于当日值的样本占比（含当日）。显示区间不改变统计窗口；实际历史不足10年时仅用可用样本。历史可能被源修订，不代表当时已发布的数据，不直接用于回测。高股息率分位不等于高估。
            </div>
          </section>
          <section className="panel research-chart-panel">
            <div className="panel-header">
              <h2>{selected.index_name} · 指数日K</h2>
              <span className="muted">指数点位，与ETF价格不同</span>
            </div>
            {loading ? (
              <div className="empty chart-empty">正在读取指数日K…</div>
            ) : !data?.candles.length ? (
              <div className="empty chart-empty">
                所选区间无本地指数日K，请检查源覆盖及采集任务。
              </div>
            ) : (
              <>
                <ChartCaption
                  title={`${code} · 指数日线`}
                  meta={`${start} ~ ${end} · 指数点位 · MA5/10/20/30/60按源收盘计算 · 来源：ChatBI指数日行情 · 生成：${chartStamp()}`}
                />
                <KLine rows={data.candles} theme={theme} indexPoints />
              </>
            )}
            <div className="panel-footer">
              实际日K覆盖：{selected.candle_first_date ?? "—"} ～{" "}
              {selected.candle_last_date ?? "—"} · {selected.candle_count}
              条。空查询区间不代表完整行情，不补价或补零。
            </div>
          </section>
          <details className="panel">
            <summary className="panel-header">数据来源与口径</summary>
            <div className="panel-footer">
              关联当前ETF：{selected.instrument_codes.join("、")}
              。来源概览日期：{selected.source_date ?? "—"}；本地快照观测：
              {stamp(selected.observed_at)}。<br />
              估值来自韭圈公开接口，PE计算方法及风险溢价国债期限未确认，未擅自标注TTM或重算。ROE历史已为百分数；源列表ROE小数不替代历史。来源概览可能截断精度，与本地按历史原值计算的分位不同。PE/PB非正值和负股息率不参与有效分位，零股息率和负风险溢价保留。
              <br />
              五类历史每天完整核验，数据库仅写新增及修订；指数日K按月首次回填、后续增量并保留七日修订交叠。不采分时、预测、成分股和相关性。
            </div>
          </details>
        </>
      )}
    </>
  );
}
