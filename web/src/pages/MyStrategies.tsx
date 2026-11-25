import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { activationMessage, journeyUrl, templateKey, type JourneyCatalog, type SavedStrategy } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import AlgorithmBacktest from "../components/AlgorithmBacktest";
import AlgorithmGuide from "../components/AlgorithmGuide";
import StrategyVersion from "../components/StrategyVersion";
import "../styles/strategy-journey.css";

export default function MyStrategies({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", edit: "", view: "list", algorithm: "", start: "", end: "" });
  const catalog = useApiResource<JourneyCatalog>("/strategies/catalog");
  const versions = useApiResource<SavedStrategy[]>("/strategies");
  const [changed, setChanged] = useState<SavedStrategy[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const rows = [...changed, ...(versions.data ?? []).filter((row) => !changed.some((item) => item.id === row.id))];
  const isDetail = query.view === "version";
  const isGuide = query.view === "algorithm";
  const isBacktest = ["backtest", "editor", "compare"].includes(query.view);
  const binding = isDetail || isBacktest ? rows.find((row) => String(row.id) === query.edit) : undefined;
  const code = binding?.instrument_code ?? (catalog.data?.instruments.some((item) => item.instrument_code === query.code) ? query.code : "");
  const replacement = binding && rows.find((row) => row.id !== binding.id && row.instrument_code === code && row.active);
  const legacy = rows.filter((row) => !row.algorithm_template_id);
  const loading = (!catalog.data && catalog.loading) || (!versions.data && versions.loading && !binding && isDetail);
  const loadError = catalog.error || (!isBacktest && !isGuide ? versions.error : "");
  const fromBinding = isBacktest && binding?.algorithm_template_id ? binding : undefined;
  const algorithm = fromBinding ? templateKey(fromBinding.template) : query.algorithm;
  const guideTemplate = catalog.data?.templates.find((item) => item.id === query.algorithm || templateKey(item) === query.algorithm);
  const range = { start: query.start || fromBinding?.settings.start_date || "", end: query.end || fromBinding?.settings.end_date || "" };

  useEffect(() => { setPending(false); setNotice(""); setError(""); }, [query.edit, query.view, code]);

  async function toggle(row: SavedStrategy) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const value = await api<SavedStrategy>(`/strategies/${row.id}/${row.active ? "pause" : "enable"}`, "POST", row.active ? undefined : { replace_active: !!replacement });
      const positions = row.active ? undefined : await api<AccountHoldings>("/account/holdings").catch(() => undefined);
      setChanged((items) => [value, ...items.filter((item) => item.id !== value.id && (item.id !== replacement?.id || row.active)),
        ...(!row.active && replacement ? [{ ...replacement, active: false }] : [])]);
      setPending(false);
      setNotice(`${row.name}${row.active ? "已暂停，历史信号仍可查看。" : `已启用。${activationMessage(value, positions)}`}`);
      versions.retry();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function openBacktest(selected = "") {
    update({ view: "backtest", edit: "", code, algorithm: selected, start: "", end: "" });
  }

  return <div className="algorithm-workspace">
    <header className="page-header"><div>
      <h1>{isDetail ? "算法绑定详情" : isGuide ? "算法说明" : isBacktest ? "算法回测" : "策略算法库"}</h1>
      <p>{isDetail ? "查看回测记录并决定是否启用每日信号。" : isGuide ? "查看当前算法的指标定义、市场含义和买卖判断口径。" : isBacktest ? "在同一只 ETF 上比较算法，检查买卖点，再决定是否绑定。" : "一套算法可用于多只 ETF；回测成功后，可以为具体标的保存绑定。"}</p>
    </div></header>
    <div className="journey-actions journey-page-controls">
      {(isDetail || isBacktest || isGuide) && <button onClick={() => update({ view: "list", edit: "", start: "", end: "", algorithm: "" })}>返回算法库</button>}
      {!isDetail && !isBacktest && !isGuide && <button className="primary" disabled={!catalog.data?.templates.length} onClick={() => openBacktest()}>开始算法对比</button>}
      {code && <a className="button-link" href={journeyUrl("etfs", code, { detail: "signals" })}>查看每日信号</a>}
    </div>
    {loadError && <p className="notice warning" role="alert">{loadError} <button onClick={() => { catalog.retry(); versions.retry(); }}>重试</button></p>}
    {error && <p className="notice warning" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {loading ? <p className="empty" role="status">正在读取算法和绑定…</p>
      : isBacktest && catalog.data ? <AlgorithmBacktest key={`${code}:${algorithm}:${range.start}:${range.end}`} catalog={catalog.data} code={code} algorithm={algorithm} range={range} theme={theme}
        onCode={(next) => update({ code: next, edit: "", algorithm, start: "", end: "" })}
        onSaved={(value) => { setChanged((items) => [value, ...items.filter((item) => item.id !== value.id)]); versions.retry(); }} />
      : isDetail ? binding ? <>
        <StrategyVersion key={binding.id} version={binding} theme={theme}>
        <section className="panel journey-inset" aria-label="管理每日信号">
          <h2>每日信号</h2>
          <p>{binding.active ? "这个绑定正在生成每日信号。" : binding.algorithm_template_id ? "已保存回测。显式启用后，从下一适用交易日开始生成信号。" : "历史绑定保留作复盘。重新回测并保存算法后可启用信号。"}</p>
          <div className="journey-actions">
            {binding.algorithm_template_id && <button onClick={() => update({ view: "backtest", algorithm: templateKey(binding.template), start: binding.settings.start_date, end: binding.settings.end_date, edit: "", code })}>重新回测算法</button>}
            {binding.active ? <button disabled={busy} onClick={() => void toggle(binding)}>暂停信号</button>
              : binding.algorithm_template_id && !pending && <button className="primary" disabled={busy} onClick={() => setPending(true)}>启用每日信号</button>}
          </div>
          {pending && <div className="notice" role="region" aria-label="确认启用算法">
            <p>{replacement ? `将替换 ${code} 当前启用的「${replacement.name}」，历史信号会保留。` : `将为 ${code} 启用「${binding.name}」。`}计划需要核验数据和仓位，不自动下单。</p>
            <div className="journey-actions"><button className="primary" disabled={busy} onClick={() => void toggle(binding)}>确认启用</button><button disabled={busy} onClick={() => setPending(false)}>取消</button></div>
          </div>}
        </section>
        </StrategyVersion>
      </> : !loadError && <p className="notice warning">找不到这个算法绑定。</p>
      : isGuide ? guideTemplate && catalog.data ? <AlgorithmGuide template={guideTemplate} templates={catalog.data.templates}
        instruments={catalog.data.instruments} code={code} onCode={(next) => update({ code: next })} />
        : !loadError && <p className="notice warning">找不到这套算法的说明。</p>
      : catalog.data && <>
        <div className="algorithm-library" aria-label="算法模板">
          {catalog.data.templates.map((item) => {
            const linked = rows.filter((row) => row.algorithm_template_id === item.id);
            const byEtf = new Map<string, SavedStrategy[]>();
            for (const row of linked.sort((a, b) => b.id - a.id)) {
              const records = byEtf.get(row.instrument_code) ?? [];
              records.push(row);
              byEtf.set(row.instrument_code, records);
            }
            const latest = [...byEtf.values()];
            return <section key={templateKey(item)} className="panel journey-inset algorithm-card">
              <header><div><h2>{item.name}</h2><span className="muted">实验算法</span></div>
                <button onClick={() => openBacktest(templateKey(item))} aria-label={`回测${item.name}`}>回测这套算法</button></header>
              <p>{item.description}</p>
              <a href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id })}>算法说明</a>
              <div className="algorithm-bindings"><h3>已绑定 {latest.length} 只 ETF</h3>
                {latest.map(([first, ...older]) => <div className="algorithm-binding" key={first.strategy_id}>
                  <span><span className="mono">{first.instrument_code}</span> · {catalog.data?.instruments.find((row) => row.instrument_code === first.instrument_code)?.instrument_name ?? "ETF"}</span>
                  <a href={journeyUrl("strategies", first.instrument_code, { view: "version", edit: String(first.id) })}>{first.active ? "查看已启用绑定" : "查看最新绑定"}</a>
                  {older.length > 0 && <details><summary>更多回测记录（{older.length}）</summary>{older.map((row) => <p key={row.id}><a href={journeyUrl("strategies", row.instrument_code, { view: "version", edit: String(row.id) })}>回测记录 #{row.id}{row.active ? " · 已启用" : ""}</a></p>)}</details>}
                </div>)}
                {latest.length === 0 && <p className="muted">{versions.loading ? "正在读取绑定…" : "回测成功后可保存绑定。"}</p>}
              </div>
            </section>;
          })}
          {!catalog.data.templates.length && <p className="empty">暂无可回测的算法。</p>}
        </div>
        {!!legacy.length && <details className="panel journey-inset"><summary>历史逐 ETF 策略（{legacy.length}）</summary>
          {legacy.map((row) => <div className="journey-saved-row" key={row.id}><span>{row.instrument_code} · {row.name}{row.active ? " · 已启用" : ""}</span><a href={journeyUrl("strategies", row.instrument_code, { view: "version", edit: String(row.id) })}>查看历史回测</a></div>)}
        </details>}
        <p className="muted">先看收益、回撤、交易笔数与买卖原因，再修订算法并用相同区间重测。实验回测不证明未来胜率。</p>
      </>}
  </div>;
}
