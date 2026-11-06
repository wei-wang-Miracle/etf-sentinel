import { useEffect, useState } from "react";
import KLine from "../components/KLine";
import { api, stamp, type Candle } from "../lib/api";

type Instrument = {
  instrument_code: string;
  instrument_name: string;
  index_name: string;
  count: number;
  first_date: string | null;
  last_date: string | null;
  estimated_holding_pct: number | null;
  reference_holding_pct: number | null;
  estimation_start_date: string;
  source_available: boolean;
  source_url: string;
  last_success_at: string;
  candle_last_date: string | null;
};
type Holding = {
  trade_date: string;
  estimated_holding_pct: number | null;
  collected_at: string;
};
type Series = {
  estimation_start_date: string;
  holdings: Holding[];
  candles: Candle[];
};
const today = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
const ratio = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}%`;

export default function NationalTeam({ theme, goJobs }: { theme: string; goJobs: () => void }) {
  const [items, setItems] = useState<Instrument[]>([]);
  const [code, setCode] = useState("");
  const [start, setStart] = useState("2026-01-01");
  const [end, setEnd] = useState(today);
  const [data, setData] = useState<Series | null>(null);
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setDirectoryLoading(true);
    setDirectoryError("");
    api<Instrument[]>("/national-team/instruments", "GET", undefined, controller.signal)
      .then((rows) => {
        setItems(rows);
        setCode((current) => current || rows[0]?.instrument_code || "");
      })
      .catch((e) => { if (!controller.signal.aborted) setDirectoryError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setDirectoryLoading(false); });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (!code) return;
    const controller = new AbortController();
    setData(null);
    setError("");
    if (!start || !end || start > end) {
      setError("请选择有效的起止日期");
      setLoading(false);
      return;
    }
    setLoading(true);
    api<Series>(`/national-team/series/${code}?start=${start}&end=${end}`, "GET", undefined, controller.signal)
      .then(setData)
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [code, start, end, refresh]);
  const selected = items.find((i) => i.instrument_code === code);
  const first = data?.holdings[0];
  const last = data?.holdings.at(-1);
  const change = first?.estimated_holding_pct != null && last?.estimated_holding_pct != null
    ? last.estimated_holding_pct - first.estimated_holding_pct : null;
  const candles = new Map(data?.candles.map((r) => [r.date, r]));
  const stale = selected?.last_date &&
    (Date.parse(`${today()}T00:00:00Z`) - Date.parse(`${selected.last_date}T00:00:00Z`)) / 86400000 > 7;
  return <>
    <header className="page-header">
      <div><h1>国家队持仓</h1><p>对照 ETF 日 K 与持仓估算，观察同一交易日的变化</p></div>
      <div className="range-buttons">
        <button onClick={() => setRefresh((n) => n + 1)}>刷新本地数据</button>
        <button className="primary" onClick={goJobs}>采集与调度</button>
      </div>
    </header>
    <div className="notice">
      持仓比例来自第三方估算，不能确认国家队真实持仓或交易。固定以 2026-01-01 起算，筛选日期不改变估算基准。
    </div>
    {(directoryError || error) && <div className="alert" role="alert">
      {directoryError || error}<button onClick={() => setRefresh((n) => n + 1)}>重试</button>
    </div>}
    <div className="panel-header holdings-directory-header">
      <h2>宽基 ETF 观察池</h2><span className="muted">已入库 {items.length} / 18 只</span>
    </div>
    <div className="instrument-chips holdings-chips">
      {items.map((item) => <button key={item.instrument_code}
        className={`instrument-chip ${item.instrument_code === code ? "active" : ""}`}
        aria-pressed={item.instrument_code === code} onClick={() => setCode(item.instrument_code)}>
        <strong>{item.index_name} <span className="mono">{item.instrument_code}</span></strong>
        <span>{item.instrument_name}</span>
      </button>)}
    </div>
    {directoryLoading && !items.length && <div className="empty" role="status">正在读取本地基金目录…</div>}
    {!directoryLoading && !directoryError && !items.length && <section className="panel empty">
      <h2>尚未采集持仓比例</h2><p>运行国家队持仓任务，采集源页面的 18 只 ETF。</p>
      <button className="primary" onClick={goJobs}>前往首次采集</button>
    </section>}
    {selected && <section className="panel">
      <div className="panel-header chart-heading">
        <div><h2>{selected.instrument_name}</h2><span className="muted mono">{code} · {selected.index_name}</span></div>
        <div className="date-controls">
          <label>起始 <input aria-label="持仓起始日期" type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></label>
          <label>截止 <input aria-label="持仓截止日期" type="date" value={end} min={start} max={today()} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
      </div>
      <div className="chart-toolbar">
        <div className="range-buttons">
          <button onClick={() => { const d = new Date(`${today()}T00:00:00Z`); d.setUTCDate(d.getUTCDate() - 90); setStart(d.toISOString().slice(0, 10)); setEnd(today()); }}>近三月</button>
          <button onClick={() => { setStart(`${today().slice(0, 4)}-01-01`); setEnd(today()); }}>今年</button>
          <button onClick={() => { setStart(selected.first_date ?? selected.estimation_start_date); setEnd(today()); }}>全部已入库</button>
        </div>
        <span className="muted">日 K 红涨绿跌 · 估算比例紫色 · 缺失不补零</span>
      </div>
      {!selected.source_available && <div className="notice warning">本次源目录缺少该基金，当前显示保留的历史数据。</div>}
      {stale && <div className="notice warning">比例源日期距今超过七天，请查看采集记录及源更新情况。</div>}
      {loading ? <div className="empty chart-empty" role="status">正在读取本地日 K 与持仓比例…</div>
        : error ? <div className="empty">查询失败，重试后查看数据。</div>
        : data && <>
          <div className="quote-strip">
            <div><span>区间末日估算比例</span><strong>{ratio(last?.estimated_holding_pct)}</strong></div>
            <div><span>区间比例变化</span><strong>{change == null ? "—" : `${change > 0 ? "+" : ""}${change.toFixed(2)} 个百分点`}</strong></div>
            <div><span>源年报基准比例 · 未核验</span><strong>{ratio(selected.reference_holding_pct)}</strong></div>
            <div><span>区间比例截止日</span><strong>{last?.trade_date ?? "—"}</strong></div>
            <div><span>区间日 K 截止日</span><strong>{data.candles.at(-1)?.date ?? "暂无日 K"}</strong></div>
          </div>
          {!data.candles.length && <div className="notice warning">该基金在所选区间暂无本地日 K，仅展示比例。持仓采集不使用外站近似价格替代行情。</div>}
          {data.holdings.length || data.candles.length
            ? <KLine rows={data.candles} holdings={data.holdings} theme={theme} />
            : <div className="empty chart-empty">所选区间暂无持仓比例或本地日 K，请调整日期或检查采集任务。</div>}
        </>}
      <div className="panel-footer">
        比例来源：<a href={selected.source_url} target="_blank" rel="noreferrer">韭圈 · national-team-etf</a>
        　·　估算基准：<span className="mono">{selected.estimation_start_date}</span>
        　·　实际比例覆盖：<span className="mono">{selected.first_date ?? "—"} ～ {selected.last_date ?? "—"}</span>
        　·　最近成功核验：<span className="mono">{stamp(selected.last_success_at)}</span>
        <br />日 K 来自本地 ChatBI 原始行情。源将份额变化用于推算国家队持仓，实际也可能来自其他投资者；比例不等于真实持仓或买卖信号。
      </div>
    </section>}
    {!loading && !error && data && data.holdings.length > 0 && <section className="panel">
      <div className="panel-header"><h2>同日对照明细</h2><span className="muted">最近 20 条 / 区间 {data.holdings.length} 条比例</span></div>
      <div className="table-scroll"><table>
        <thead><tr><th>源交易日期</th><th className="number">估算持仓比例</th><th className="number">本地收盘价（元）</th><th className="number">日涨跌幅</th><th>比例入库 / 修订时间</th></tr></thead>
        <tbody>{data.holdings.slice(-20).reverse().map((r) => {
          const candle = candles.get(r.trade_date);
          return <tr key={r.trade_date}><td className="mono">{r.trade_date}</td>
            <td className="number">{ratio(r.estimated_holding_pct)}</td>
            <td className="number">{candle?.close.toFixed(4) ?? "—"}</td>
            <td className={`number ${candle?.change_pct == null ? "" : candle.change_pct >= 0 ? "market-up" : "market-down"}`}>{ratio(candle?.change_pct)}</td>
            <td className="mono">{stamp(r.collected_at)}</td></tr>;
        })}</tbody>
      </table></div>
    </section>}
  </>;
}
