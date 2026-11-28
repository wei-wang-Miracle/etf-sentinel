import { useState } from "react";
import AlgorithmBacktest from "../components/AlgorithmBacktest";
import AppLink from "../components/AppLink";
import { api } from "../lib/api";
import { useResearchQuery } from "../lib/research";
import {
  evidenceForStrategy,
  evidenceTierLabel,
  isStrategyAdoptable,
  journeyUrl,
  strategyScopeLabel,
  type JourneyCatalog,
  type StrategyAssignment,
} from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import "../styles/strategy-journey.css";

const roles: Record<string, string> = { trigger: "入场结构", confirmation: "入场确认", risk: "风险判断", filter: "过滤", exit: "退出" };

export default function MyStrategies({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", view: "list", algorithm: "", start: "", end: "", from: "" });
  const catalog = useApiResource<JourneyCatalog>("/strategies/catalog");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const instrument = catalog.data?.instruments.find((item) => item.instrument_code === query.code);
  const code = instrument ? query.code : "";
  const isBacktest = query.view === "backtest";
  const isGuide = query.view === "algorithm";
  const visibleStrategies = catalog.data?.strategies.filter(
    (item) => !code || item.supported_instruments.includes(code),
  ) ?? [];
  const selected = catalog.data?.strategies.find((item) => item.id === query.algorithm);
  const selectedEvidence = evidenceForStrategy(selected, instrument?.research_category);
  const selectedAdoptable = code ? isStrategyAdoptable(selected, code) : selected?.adoptable !== false;
  const dates = { ...(query.start ? { start: query.start } : {}), ...(query.end ? { end: query.end } : {}) };

  async function pause(row: StrategyAssignment) {
    setBusy(row.instrument_code); setError(""); setMessage("");
    try {
      await api(`/strategies/${row.instrument_code}/pause`, "POST");
      catalog.retry();
      setMessage(`${row.instrument_code} 已暂停后续信号，原有计划仍可复盘。`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }

  function backtest(algorithm = "", instrument = code, keepDates = true) {
    update({
      view: "backtest",
      algorithm,
      code: instrument,
      from: "",
      ...(keepDates ? dates : { start: "", end: "" }),
    });
  }

  return <div className="algorithm-workspace">
    <header className="page-header"><div><h1>{isBacktest ? "策略回测" : isGuide ? "策略说明" : "我的策略"}</h1></div></header>
    <div className="journey-actions journey-page-controls">
      {isGuide && query.from === "backtest" && <button className="primary" onClick={() => update({ view: "backtest", algorithm: "", from: "" })}>返回策略对比</button>}
      {isBacktest || isGuide ? <button onClick={() => update({ view: "list", algorithm: "", from: "" })}>返回策略库</button>
        : <button className="primary" disabled={!catalog.data?.strategies.length} onClick={() => backtest()}>开始策略对比</button>}
      {code && <AppLink className="button-link" href={journeyUrl("etfs", code, { detail: "signals", ...dates })}>查看每日信号</AppLink>}
    </div>
    {catalog.loading && !catalog.data && <p role="status">正在读取策略目录…</p>}
    {catalog.error && <p className="notice warning" role="alert">{catalog.error} <button onClick={catalog.retry}>重试</button></p>}
    {error && <p className="notice warning" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {catalog.data && (isBacktest ? <AlgorithmBacktest key={`${code}:${query.algorithm}:${query.start}:${query.end}`} catalog={catalog.data} code={code} algorithm={query.algorithm}
      range={{ start: query.start, end: query.end }} theme={theme} onCode={(next) => update({ code: next, start: "", end: "" })} onAdopted={catalog.retry} />
      : isGuide ? selected ? <section className="panel journey-inset algorithm-guide">
        <h2>{selected.name}{!selectedAdoptable ? " · 比较观察" : ""}</h2>
        <p className="muted">
          {strategyScopeLabel(selected)}
          {selectedEvidence ? ` · ${evidenceTierLabel(selectedEvidence)}（${selectedEvidence.research_version}）` : ""}
        </p>
        <p>{selected.description}</p>
        {selectedEvidence?.evidence_summary?.note && <p className="notice">{selectedEvidence.evidence_summary.note}</p>}
        <h3>策略使用的因子</h3><dl>{selected.factors.map((factor) => <div key={factor.id}>
          <dt><strong>{factor.name}</strong> · {roles[factor.role]} · {factor.category}</dt><dd>{factor.meaning}</dd>
        </div>)}</dl>
        <p className="muted">单个因子不等于买卖信号。策略还会检查风险、止损、止盈与持有时间。{!selectedAdoptable ? "该策略当前仅用于研究比较观察，暂不开放用于盘前信号。" : ""}</p>
        <button onClick={() => backtest(selected.id)}>回测这套策略</button>
      </section> : <p className="empty">该策略不在当前目录中。</p>
      : <>
        <section className="panel journey-inset" aria-label="当前采用">
          <h2>当前采用</h2>
          {!catalog.data.assignments.length && <p className="muted">还没有采用策略。回测不会自动启用每日信号。</p>}
          {catalog.data.assignments.map((row) => <div className="journey-saved-row" key={row.id}>
            <span><span className="mono">{row.instrument_code}</span> · {catalog.data?.strategies.find((item) => item.id === row.strategy_id)?.name ?? row.strategy_id} · {row.active ? "已启用" : "已暂停"}</span>
            <div className="journey-actions">
              <AppLink href={journeyUrl("etfs", row.instrument_code, { detail: "overview", tab: "price" })}>查看行情</AppLink>
              <AppLink href={journeyUrl("etfs", row.instrument_code, { detail: "signals" })}>查看信号</AppLink>
              <button onClick={() => backtest(row.strategy_id, row.instrument_code, false)}>对比回测</button>
              {row.active && <button disabled={!!busy || catalog.loading} onClick={() => void pause(row)}>暂停信号</button>}
            </div>
          </div>)}
        </section>
        {code && !!visibleStrategies.length && <p className="muted">当前关注 <span className="mono">{code}</span>（{instrument?.research_category ?? "未分类"}），策略库展示通用策略及该分类绑定策略。</p>}
        <div className="algorithm-library" aria-label="策略库">{visibleStrategies.map((item) => {
          const itemEvidence = evidenceForStrategy(item, instrument?.research_category);
          const itemAdoptable = code ? isStrategyAdoptable(item, code) : item.adoptable !== false;
          return <section className="panel journey-inset algorithm-card" key={item.id}>
            <header><h2>{item.name}{!itemAdoptable ? "（比较观察）" : ""}</h2><button onClick={() => backtest(item.id)} aria-label={`回测${item.name}`}>回测这套策略</button></header>
            <p className="muted">{strategyScopeLabel(item)}{itemEvidence ? ` · ${evidenceTierLabel(itemEvidence)}` : ""}</p>
            <p>{item.description}</p>
            <AppLink href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id, ...dates })}>策略说明</AppLink>
          </section>;
        })}</div>
        {!visibleStrategies.length && <p className="empty">当前策略库已清空（保留 50 项原子因子观察与回测引擎），等待后续结合研究重新登记策略。</p>}
      </>)}
  </div>;
}
