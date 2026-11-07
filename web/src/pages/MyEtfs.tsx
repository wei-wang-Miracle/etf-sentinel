import { useEffect, useState } from "react";
import { api, type Instrument } from "../lib/api";
import { type AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { journeyUrl, type SavedStrategy } from "../lib/strategyJourney";
import DailySignals from "../components/DailySignals";
import EtfReview from "../components/EtfReview";
import ResearchObject from "./ResearchObject";

export default function MyEtfs({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", object: "", detail: "operations" });
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [holdings, setHoldings] = useState<AccountHoldings>();
  const [versions, setVersions] = useState<SavedStrategy[]>([]);
  const [search, setSearch] = useState(""), [scope, setScope] = useState("held");
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    Promise.all([api<Instrument[]>("/instruments", "GET", undefined, controller.signal), api<AccountHoldings>("/account/holdings", "GET", undefined, controller.signal), api<SavedStrategy[]>("/strategies", "GET", undefined, controller.signal)])
      .then(([items, positions, rows]) => { if (!controller.signal.aborted) { setInstruments(items); setHoldings(positions); setVersions(rows); } })
      .catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);
  const held = new Set(holdings?.items.filter((row) => row.current_amount > 0).map((row) => row.instrument_code));
  const code = query.code || (query.object.startsWith("etf:") ? query.object.slice(4) : "");
  const list = instruments.filter((row) => (scope === "all" || held.size === 0 || held.has(row.code)) && `${row.code}${row.name}`.includes(search.trim()));
  return <>
    <header className="page-header"><div><h1>我的 ETF</h1><p>先了解一只 ETF 与自己的操作，再制定能解释的策略</p></div><a href={journeyUrl("etfs", undefined, { auxiliary: "compare" })}>跨 ETF 数据对比</a></header>
    {error && <p className="alert" role="alert">{error}<button onClick={() => setRefresh((old) => old + 1)}>重试</button></p>}
    {query.object.startsWith("index:") ? <ResearchObject theme={theme} /> : !code ? <>
      <DailySignals compact />
      <section className="panel journey-inset"><div className="journey-section-heading"><h2>选择一只 ETF</h2><span className="muted mono">持仓来源：{holdings?.as_of ?? "尚未同步"}</span></div><div className="journey-actions"><button aria-pressed={scope === "held"} onClick={() => setScope("held")}>当前持仓</button><button aria-pressed={scope === "all"} onClick={() => setScope("all")}>全部 ETF</button><label>代码／名称<input type="search" placeholder="搜索 ETF" value={search} onChange={(e) => setSearch(e.target.value)} /></label></div>
        {!held.size && !loading && <p className="notice">没有可展示的当前正持仓，已展示全部配置 ETF，可直接研究未持仓标的。</p>}
        {loading ? <p className="empty" role="status">正在读取 ETF 与持仓状态…</p> : <div className="journey-etf-list">{list.map((row) => <article key={row.code} className="journey-etf-row"><div><h3>{row.name} <span className="mono muted">{row.code}</span></h3><p className="muted">{held.has(row.code) ? "当前持仓" : holdings?.as_of ? "当前未持仓" : "仓位待同步"} · 行情截至 {row.last_date ?? "暂无行情"}</p></div><div><p className="muted">{versions.find((version) => version.active && version.instrument_code === row.code)?.name ?? "尚无运行策略"}</p><a href={journeyUrl("etfs", row.code)}>查看这只 ETF →</a></div></article>)}{!list.length && <p className="empty">没有匹配的 ETF，请调整搜索或到数据管理配置。</p>}</div>}
      </section>
    </> : <>
      <div className="journey-actions journey-page-controls"><a href={journeyUrl("etfs")}>← 返回 ETF 列表</a><label>当前 ETF<select value={code} onChange={(e) => update({ code: e.target.value, object: `etf:${e.target.value}` })}>{instruments.map((row) => <option key={row.code} value={row.code}>{row.code} · {row.name}</option>)}</select></label><a className="journey-primary-link" href={journeyUrl("strategies", code, { view: "editor" })}>为它创建策略／比较其他策略</a></div>
      <div className="research-tabs" aria-label="ETF 使用步骤">{[["overview", "走势与数据背景"], ["operations", "了解自己的操作"], ["signals", "每日信号与执行"]].map(([value, label]) => <button key={value} aria-selected={query.detail === value} onClick={() => update({ detail: value, code, object: `etf:${code}` })}>{label}</button>)}</div>
      {query.detail === "operations" ? <EtfReview key={code} theme={theme} fixedObject /> : query.detail === "signals" ? <DailySignals key={code} code={code} /> : <ResearchObject key={code} theme={theme} fixedObject={query.object.startsWith("etf:")} />}
    </>}
  </>;
}
