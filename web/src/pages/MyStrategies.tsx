import { useCallback, useEffect, useState } from "react";
import { api, stamp } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { activationMessage, journeyUrl, type JourneyCatalog, ruleSummary, type SavedStrategy } from "../lib/strategyJourney";
import StrategyEditor from "../components/StrategyEditor";
import DailySignals from "../components/DailySignals";
import Backtests from "./Backtests";

export default function MyStrategies({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", edit: "", view: "list" });
  const [catalog, setCatalog] = useState<JourneyCatalog>();
  const [versions, setVersions] = useState<SavedStrategy[]>([]);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<SavedStrategy>();
  const refresh = useCallback(async () => {
    const [data, rows] = await Promise.all([api<JourneyCatalog>("/strategies/catalog"), api<SavedStrategy[]>("/strategies")]);
    setCatalog(data); setVersions(rows);
  }, []);
  useEffect(() => { let cancelled = false; refresh().catch((e) => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading(false); }); return () => { cancelled = true; }; }, [refresh]);
  async function toggle(row: SavedStrategy) {
    setBusy(true); setError(""); setNotice("");
    try {
      const value = await api<SavedStrategy>(`/strategies/${row.id}/${row.active ? "pause" : "enable"}`, "POST", row.active ? undefined : { replace_active: true });
      const positions = row.active ? undefined : await api<AccountHoldings>("/account/holdings").catch(() => undefined);
      setPending(undefined); setNotice(`${row.name} · 第 ${row.version} 版已${row.active ? "暂停，历史记录保留。" : `启用。${activationMessage(value, positions)}`}`); await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const edit = versions.find((row) => String(row.id) === query.edit);
  const code = (query.view === "editor" && edit ? edit.instrument_code : catalog?.instruments.some((row) => row.instrument_code === query.code) ? query.code : "");
  useEffect(() => { setPending(undefined); setNotice(""); }, [code]);
  if (query.view === "legacy" || new URLSearchParams(location.search).has("run_id")) return <><a href={journeyUrl("strategies")}>← 返回我的策略</a><Backtests theme={theme} /></>;
  return <>
    <header className="page-header"><div><h1>{query.view === "editor" ? edit ? "基于版本修改" : "创建策略" : "我的策略"}</h1><p>保存不同方法，在同一只 ETF 上比较，再决定是否每日运行</p></div><a href={journeyUrl("strategies", undefined, { view: "legacy" })}>历史实验与旧观察记录</a></header>
    {error && <p className="alert" role="alert">{error}<button onClick={() => void refresh().then(() => setError("")).catch((e) => setError(e.message))}>重试</button></p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="journey-actions journey-page-controls"><label>当前 ETF <select aria-label="当前 ETF" value={code} disabled={busy || loading || query.view === "editor"} onChange={(e) => update({ code: e.target.value, edit: "", view: "list" })}><option value="">选择 ETF</option>{catalog?.instruments.map((row) => <option key={row.instrument_code} value={row.instrument_code}>{row.instrument_code} · {row.instrument_name}</option>)}</select></label>{query.view === "list" && <button disabled={!code || loading} className="primary" onClick={() => update({ view: "editor", edit: "", code, stage: "rules" })}>创建新策略</button>}<button disabled={!code || loading} onClick={() => update({ view: "list", edit: "" })}>{query.view === "list" ? "查看策略与信号" : "返回版本列表"}</button></div>
    {loading ? <div className="empty" role="status">正在读取已保存策略…</div> : !code ? <div className="empty"><p>先选择一只 ETF</p><a href={journeyUrl("data")}>配置标的</a></div> : query.view === "version" ? !edit || edit.instrument_code !== code ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <section className="panel journey-inset"><h2>{edit.name} · 第 {edit.version} 版</h2><p>已保存版本 · 只读</p><p>{ruleSummary(edit.rule, catalog?.conditions ?? [], catalog?.sentiment_categories ?? [])}</p><p>研究区间 {edit.settings.start_date}—{edit.settings.end_date} · 本金 {edit.settings.initial_cash} 元</p><button className="primary" onClick={() => update({ view: "editor", code: edit.instrument_code, edit: String(edit.id), stage: "rules" })}>基于此版本修改</button></section> : query.view === "editor" ? query.edit && (!edit || edit.instrument_code !== code) ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <StrategyEditor key={`${code}:${edit?.id ?? "new"}`} code={code} initial={edit} theme={theme} onSaved={() => void refresh().catch((e) => setError(e.message))} /> : <>
      <section className="panel journey-inset"><h2>已保存的方法</h2><p className="muted">一个 ETF 可保存多种策略及历史版本，同一时间只启用一条。</p><div className="journey-saved-list">{versions.filter((row) => row.instrument_code === code).map((row) => <article key={row.id} className="journey-saved-row"><div><h3>{row.name} <span className="muted">第 {row.version} 版</span></h3><p className="muted">{stamp(row.created_at)} · {row.rule.allocation === 50 ? "半资金" : "全部资金"} · {row.active ? "正在每日运行" : "未启用"}</p></div><div className="journey-actions"><button disabled={busy} onClick={() => update({ view: "version", edit: String(row.id), code: row.instrument_code })}>查看版本</button><button disabled={busy} onClick={() => row.active ? void toggle(row) : setPending(row)}>{row.active ? "暂停" : "启用这个版本"}</button></div></article>)}{!versions.some((row) => row.instrument_code === code) && <div className="empty">还没有保存策略。先配置条件并与一直持有比较。</div>}</div></section>
      {pending && pending.instrument_code === code && <section className="panel journey-inset" role="region" aria-label="确认启用策略"><h2>{catalog?.instruments.find((row) => row.instrument_code === pending.instrument_code)?.instrument_name} {pending.instrument_code} · 确认启用“{pending.name}”第 {pending.version} 版</h2><p>{versions.some((row) => row.active && row.instrument_code === pending.instrument_code) ? `这将替换 ${versions.find((row) => row.active && row.instrument_code === pending.instrument_code)?.name} 第 ${versions.find((row) => row.active && row.instrument_code === pending.instrument_code)?.version} 版，保留历史信号和执行记录。` : "从下一适用交易日开始准备计划，不补写过去的信号。"}下一适用日期、就绪状态和下次运行待服务端核验；不补历史、不自动下单。启用不代表真实账户已经买入或卖出。</p><div className="journey-actions"><button className="primary" disabled={busy} onClick={() => void toggle(pending)}>确认启用</button><button disabled={busy} onClick={() => setPending(undefined)}>取消</button></div></section>}
      <DailySignals key={`${code}:${versions.filter((row) => row.active && row.instrument_code === code).map((row) => row.id).join(",")}`} code={code} compact />
    </>}
  </>;
}
