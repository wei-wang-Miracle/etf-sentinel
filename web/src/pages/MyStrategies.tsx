import { useCallback, useEffect, useState } from "react";
import { api, stamp } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { activationMessage, journeyUrl, type JourneyCatalog, type SavedStrategy } from "../lib/strategyJourney";
import StrategyEditor from "../components/StrategyEditor";
import StrategyVersion from "../components/StrategyVersion";
import DailySignals from "../components/DailySignals";

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
  const codeVersions = versions.filter((row) => row.instrument_code === code);
  const hasActive = codeVersions.some((row) => row.active);
  useEffect(() => { setPending(undefined); setNotice(""); }, [code]);
  return <div className={query.view === "editor" && code ? "strategy-create-page" : undefined}>
    <header className="page-header"><div><h1>{query.view === "editor" ? edit ? "基于版本修改" : "创建策略" : query.view === "compare" ? "已有策略回测比较" : "我的策略"}</h1><p>保存不同方法，在同一只 ETF 上比较，再决定是否每日运行</p></div></header>
    {error && <p className="alert" role="alert">{error}<button onClick={() => void refresh().then(() => setError("")).catch((e) => setError(e.message))}>重试</button></p>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="journey-actions journey-page-controls"><label>当前 ETF <select aria-label="当前 ETF" value={code} disabled={busy || loading || query.view === "editor"} onChange={(e) => update({ code: e.target.value, edit: "", view: "list" })}><option value="">选择 ETF</option>{catalog?.instruments.map((row) => <option key={row.instrument_code} value={row.instrument_code}>{row.instrument_code} · {row.instrument_name}</option>)}</select></label>{query.view === "list" && <button disabled={!code || loading} className="primary" onClick={() => update({ view: "editor", edit: "", code, stage: "rules" })}>创建新策略</button>}<button disabled={!code || loading} onClick={() => query.view === "list" ? update({ page: "etfs", detail: "signals", code, edit: "", auxiliary: "" }) : update({ view: "list", edit: "" })}>{query.view === "list" ? "查看策略与信号" : "返回版本列表"}</button>{query.view === "compare" && <button onClick={() => update({ view: "version" })}>返回版本详情</button>}</div>
    {loading ? <div className="empty" role="status">正在读取已保存策略…</div> : !code ? <><div className="empty"><p>先选择一只 ETF</p><a href={journeyUrl("data")}>配置标的</a></div><section className="panel journey-guide" role="region" aria-label="策略流程指引"><h2>策略研究怎么走</h2><ol className="journey-guide-steps"><li><strong>选择 ETF</strong><span>持仓或全部配置内 ETF 均可研究</span></li><li><strong>配置买卖条件</strong><span>中文指标自由组合，也可从趋势模板开始</span></li><li><strong>回测验证</strong><span>与一直持有、已保存版本在同一假设下比较</span></li><li><strong>保存命名版本</strong><span>回测满意再保存，历史版本不被覆盖</span></li><li><strong>启用每日信号</strong><span>启用后每个交易日 08:30 生成盘前计划</span></li></ol><p className="muted">回测是历史模拟；信号不等于成交，不自动下单。</p></section></> : query.view === "version" ? !edit || edit.instrument_code !== code ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <StrategyVersion key={edit.id} version={edit} catalog={catalog} theme={theme} onCompare={() => update({ view: "compare", stage: "compare" })} onEdit={() => update({ view: "editor", code: edit.instrument_code, edit: String(edit.id), stage: "rules" })} /> : query.view === "compare" ? !edit || edit.instrument_code !== code ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <StrategyEditor key={`compare:${edit.id}`} code={code} initial={edit} theme={theme} savedOnly onSaved={() => {}} /> : query.view === "editor" ? query.edit && (!edit || edit.instrument_code !== code) ? <div className="notice warning">策略版本不存在或已不属于当前ETF，请重新选择。</div> : <StrategyEditor key={`${code}:${edit?.id ?? "new"}`} code={code} initial={edit} theme={theme} onSaved={() => void refresh().catch((e) => setError(e.message))} /> : <>
      {!hasActive && <p className="notice journey-next-step">{codeVersions.length ? "回测满意后，启用一个版本，系统才会在每个交易日盘前生成信号。" : "还没有保存策略。创建第一个策略：配置条件后先回测，满意再保存。"}</p>}
      <section className="panel journey-inset"><h2>已保存的方法</h2><p className="muted">一个 ETF 可保存多种策略及历史版本，同一时间只启用一条。</p><div className="journey-saved-list">{versions.filter((row) => row.instrument_code === code).map((row) => <article key={row.id} className="journey-saved-row"><div><h3>{row.name} <span className="muted">第 {row.version} 版</span></h3><p className="muted">{stamp(row.created_at)} · {row.rule.allocation === 50 ? "半资金" : "全部资金"} · {row.active ? "正在每日运行" : "未启用"}</p></div><div className="journey-actions"><button disabled={busy} onClick={() => update({ view: "version", edit: String(row.id), code: row.instrument_code })}>查看版本</button><button disabled={busy} onClick={() => row.active ? void toggle(row) : setPending(row)}>{row.active ? "暂停" : "启用这个版本"}</button></div></article>)}</div></section>
      {pending && pending.instrument_code === code && <section className="panel journey-inset" role="region" aria-label="确认启用策略"><h2>{catalog?.instruments.find((row) => row.instrument_code === pending.instrument_code)?.instrument_name} {pending.instrument_code} · 确认启用“{pending.name}”第 {pending.version} 版</h2><p>{versions.some((row) => row.active && row.instrument_code === pending.instrument_code) ? `这将替换 ${versions.find((row) => row.active && row.instrument_code === pending.instrument_code)?.name} 第 ${versions.find((row) => row.active && row.instrument_code === pending.instrument_code)?.version} 版，保留历史信号和执行记录。` : "从下一适用交易日开始准备计划，不补写过去的信号。"}下一适用日期、就绪状态和下次运行待服务端核验；不补历史、不自动下单。启用不代表真实账户已经买入或卖出。</p><div className="journey-actions"><button className="primary" disabled={busy} onClick={() => void toggle(pending)}>确认启用</button><button disabled={busy} onClick={() => setPending(undefined)}>取消</button></div></section>}
      <DailySignals key={`${code}:${versions.filter((row) => row.active && row.instrument_code === code).map((row) => row.id).join(",")}`} code={code} compact />
    </>}
  </div>;
}
