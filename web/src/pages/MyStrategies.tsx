import { useState } from "react";
import AlgorithmBacktest from "../components/AlgorithmBacktest";
import { api } from "../lib/api";
import { useResearchQuery } from "../lib/research";
import { journeyUrl, type JourneyCatalog, type StrategyAssignment } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import "../styles/strategy-journey.css";

const roles: Record<string, string> = { trigger: "入场结构", confirmation: "入场确认", risk: "风险判断", filter: "过滤", exit: "退出" };

export default function MyStrategies({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", view: "list", algorithm: "", start: "", end: "" });
  const catalog = useApiResource<JourneyCatalog>("/strategies/catalog");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const code = catalog.data?.instruments.some((item) => item.instrument_code === query.code) ? query.code : "";
  const isBacktest = query.view === "backtest";
  const isGuide = query.view === "algorithm";
  const selected = catalog.data?.strategies.find((item) => item.id === query.algorithm);

  async function pause(row: StrategyAssignment) {
    setBusy(row.instrument_code); setError(""); setMessage("");
    try {
      await api(`/strategies/${row.instrument_code}/pause`, "POST");
      catalog.retry();
      setMessage(`${row.instrument_code} 已暂停后续信号，原有计划仍可复盘。`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }

  function backtest(algorithm = "", instrument = code) {
    update({ view: "backtest", algorithm, code: instrument, start: "", end: "" });
  }

  return <div className="algorithm-workspace">
    <header className="page-header"><div><h1>{isBacktest ? "策略回测" : isGuide ? "策略说明" : "我的策略"}</h1></div></header>
    <div className="journey-actions journey-page-controls">
      {isBacktest || isGuide ? <button onClick={() => update({ view: "list", algorithm: "" })}>返回策略库</button>
        : <button className="primary" disabled={!catalog.data?.strategies.length} onClick={() => backtest()}>开始策略对比</button>}
      {code && <a className="button-link" href={journeyUrl("etfs", code, { detail: "signals" })}>查看每日信号</a>}
    </div>
    {catalog.loading && !catalog.data && <p role="status">正在读取策略目录…</p>}
    {catalog.error && <p className="notice warning" role="alert">{catalog.error} <button onClick={catalog.retry}>重试</button></p>}
    {error && <p className="notice warning" role="alert">{error}</p>}
    {message && <p className="notice" role="status">{message}</p>}
    {catalog.data && (isBacktest ? <AlgorithmBacktest key={`${code}:${query.algorithm}:${query.start}:${query.end}`} catalog={catalog.data} code={code} algorithm={query.algorithm}
      range={{ start: query.start, end: query.end }} theme={theme} onCode={(next) => update({ code: next, start: "", end: "" })} onAdopted={catalog.retry} />
      : isGuide ? selected ? <section className="panel journey-inset algorithm-guide">
        <h2>{selected.name}</h2><p>{selected.description}</p>
        <h3>策略使用的因子</h3><dl>{selected.factors.map((factor) => <div key={factor.id}>
          <dt><strong>{factor.name}</strong> · {roles[factor.role]} · {factor.category}</dt><dd>{factor.meaning}</dd>
        </div>)}</dl>
        <p className="muted">单个因子不等于买卖信号。策略还会检查风险、止损、止盈与持有时间。</p>
        <button onClick={() => backtest(selected.id)}>回测这套策略</button>
      </section> : <p className="empty">该策略不在当前目录中。</p>
      : <>
        <section className="panel journey-inset" aria-label="当前采用">
          <h2>当前采用</h2>
          {!catalog.data.assignments.length && <p className="muted">还没有采用策略。回测不会自动启用每日信号。</p>}
          {catalog.data.assignments.map((row) => <div className="journey-saved-row" key={row.id}>
            <span><span className="mono">{row.instrument_code}</span> · {catalog.data?.strategies.find((item) => item.id === row.strategy_id)?.name ?? row.strategy_id} · {row.active ? "已启用" : "已暂停"}</span>
            <div className="journey-actions">
              <a href={journeyUrl("etfs", row.instrument_code, { detail: "signals" })}>查看信号</a>
              <button onClick={() => backtest(row.strategy_id, row.instrument_code)}>对比回测</button>
              {row.active && <button disabled={!!busy || catalog.loading} onClick={() => void pause(row)}>暂停信号</button>}
            </div>
          </div>)}
        </section>
        <div className="algorithm-library" aria-label="策略库">{catalog.data.strategies.map((item) => <section className="panel journey-inset algorithm-card" key={item.id}>
          <header><h2>{item.name}</h2><button onClick={() => backtest(item.id)} aria-label={`回测${item.name}`}>回测这套策略</button></header>
          <p>{item.description}</p>
          <a href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id })}>策略说明</a>
        </section>)}</div>
        {!catalog.data.strategies.length && <p className="empty">暂无可回测策略。</p>}
      </>)}
  </div>;
}
