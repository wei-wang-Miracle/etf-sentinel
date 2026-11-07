import { useCallback, useEffect, useState } from "react";
import { api, stamp } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { activationMessage, journeyUrl, type JourneyCatalog, type SavedStrategy } from "../lib/strategyJourney";
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
  const code = query.code || edit?.instrument_code || catalog?.instruments[0]?.instrument_code || "";
  useEffect(() => { setPending(undefined); setNotice(""); }, [code]);
  if (query.view === "legacy" || new URLSearchParams(location.search).has("run_id")) return <><a href={journeyUrl("strategies")}>← 返回我的策略</a><Backtests theme={theme} /></>;
  return <>
    <header className="page-header"><div><h1>我的策略</h1><p>保存不同方法，在同一只 ETF 上比较，再决定是否每日运行</p></div><a href={journeyUrl("strategies", undefined, { view: "legacy" })}>历史实验与旧观察记录</a></header>
    {error && <p className="alert" role="alert">{error}<button onClick={() => void refresh().then(() => setError("")).catch((e) => setError(e.message))}>重试</button></p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="journey-actions journey-page-controls"><label>ETF <select value={code} disabled={busy || loading} onChange={(e) => update({ code: e.target.value, edit: "", view: "list" })}>{catalog?.instruments.map((row) => <option key={row.instrument_code} value={row.instrument_code}>{row.instrument_code} · {row.instrument_name}</option>)}</select></label><button disabled={!code || loading} className="primary" onClick={() => update({ view: "editor", edit: "", code })}>创建新策略</button><button disabled={!code || loading} onClick={() => update({ view: "list", edit: "" })}>查看策略与信号</button></div>
    {loading ? <div className="empty" role="status">正在读取已保存策略…</div> : !code ? <div className="empty">尚无配置内 ETF。<a href={journeyUrl("data")}>配置标的</a></div> : query.view === "editor" ? query.edit && (!edit || edit.instrument_code !== code) ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <StrategyEditor key={`${code}:${edit?.id ?? "new"}`} code={code} initial={edit} theme={theme} onSaved={() => void refresh().catch((e) => setError(e.message))} /> : <>
      <section className="panel journey-inset"><h2>已保存的方法</h2><p className="muted">一个 ETF 可保存多种策略及历史版本，同一时间只启用一条。</p><div className="journey-saved-list">{versions.filter((row) => row.instrument_code === code).map((row) => <article key={row.id} className="journey-saved-row"><div><h3>{row.name} <span className="muted">第 {row.version} 版</span></h3><p className="muted">{stamp(row.created_at)} · {row.rule.allocation === 50 ? "半资金" : "全部资金"} · {row.active ? "正在每日运行" : "已保存／暂停"}</p></div><div className="journey-actions"><button disabled={busy} onClick={() => update({ view: "editor", edit: String(row.id), code: row.instrument_code })}>编辑／回测比较</button><button disabled={busy} onClick={() => row.active ? void toggle(row) : setPending(row)}>{row.active ? "暂停" : "启用这个版本"}</button></div></article>)}{!versions.some((row) => row.instrument_code === code) && <div className="empty">还没有保存策略。先配置条件并与一直持有比较。</div>}</div></section>
      {pending && pending.instrument_code === code && <section className="panel journey-inset" role="region" aria-label="确认启用策略"><h2>{pending.instrument_code} · 确认启用“{pending.name}”第 {pending.version} 版</h2><p>{versions.some((row) => row.active && row.instrument_code === pending.instrument_code) ? "这将暂停同 ETF 当前运行的策略，保留历史信号和执行记录。" : "从下一适用交易日开始准备计划，不补写过去的信号。"}启用不代表真实账户已经买入或卖出。</p><div className="journey-actions"><button className="primary" disabled={busy} onClick={() => void toggle(pending)}>确认启用</button><button disabled={busy} onClick={() => setPending(undefined)}>取消</button></div></section>}
      <DailySignals key={`${code}:${versions.filter((row) => row.active && row.instrument_code === code).map((row) => row.id).join(",")}`} code={code} />
    </>}
  </>;
}
