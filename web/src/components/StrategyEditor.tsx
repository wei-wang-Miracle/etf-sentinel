import { useEffect, useId, useRef, useState } from "react";
import { api } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { dateAgo } from "../lib/research";
import {
  activationMessage, journeyUrl, operatorNames, ruleSummary, trendRule,
  type Comparison, type Condition, type ConditionDefinition, type ConditionGroup,
  type Coverage, type Draft, type JourneyCatalog, type Rule, type SavedStrategy,
} from "../lib/strategyJourney";
import StrategyComparison from "./StrategyComparison";
import { strategyIndicatorHelp } from "../lib/strategyIndicatorHelp";

const coverageNames: Record<string, string> = { historical: "可用于历史回测", revised: "可做修订历史研究", unavailable: "当前不能使用" };

function ConditionCard({ title, group, definitions, categories, coverage, onChange, disabled }: {
  title: string; group: ConditionGroup; definitions: ConditionDefinition[];
  categories: JourneyCatalog["sentiment_categories"]; coverage?: Coverage;
  onChange: (group: ConditionGroup) => void; disabled: boolean;
}) {
  const [more, setMore] = useState(false);
  const [helpIndex, setHelpIndex] = useState<number>();
  const helpPrefix = useId();
  const update = (index: number, patch: Partial<Condition>) => onChange({ ...group, conditions: group.conditions.map((row, i) => i === index ? { ...row, ...patch } : row) });
  const duplicate = group.conditions.some((row, i) => group.conditions.some((other, j) => i !== j && row.indicator === other.indicator && row.window === other.window));
  return <fieldset className="journey-rule-card" disabled={disabled}>
    <legend>{title}</legend>
    <label>触发方式 <select value={group.mode} onChange={(e) => onChange({ ...group, mode: e.target.value as ConditionGroup["mode"] })}><option value="all">全部条件满足</option><option value="any">任一条件满足</option></select></label>
    {group.conditions.map((row, index) => {
      const definition = definitions.find((item) => item.key === row.indicator);
      const available = coverage?.conditions.find((item) => item.key === row.indicator);
      const help = strategyIndicatorHelp[row.indicator];
      const helpId = `${helpPrefix}-${index}`;
      const helpOpen = helpIndex === index && !!help;
      const describedBy = helpOpen ? `${helpId}-meaning` : undefined;
      return <div className="journey-condition" key={index}>
        <div className="journey-condition-inputs" onFocusCapture={(e) => {
          if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) setHelpIndex(index);
        }}><label>条件 {index + 1}<select aria-describedby={describedBy} value={row.indicator} onChange={(e) => {
          setHelpIndex(index);
          const next = definitions.find((item) => item.key === e.target.value);
          const condition: Condition = { indicator: e.target.value, operator: row.operator, threshold: "0", ...(next?.window ? { window: 20 } : {}), ...(e.target.value === "sentiment" ? { category_key: "" } : {}) };
          onChange({ ...group, conditions: group.conditions.map((item, i) => i === index ? condition : item) });
        }}>{definitions.filter((item) => more || item.key === "trend" || item.key === "momentum" || item.key === row.indicator).map((item) => <option key={item.key} value={item.key}>{item.label}{coverage?.conditions.find((c) => c.key === item.key)?.status === "unavailable" ? " · 暂不可用" : ""}</option>)}</select></label>
        {definition?.window && <label>回看交易日<input aria-describedby={describedBy} type="number" min={2} max={250} required value={row.window ?? 20} onChange={(e) => update(index, { window: Number(e.target.value) })} /></label>}
        {row.indicator === "sentiment" && <label>市场背景类别<select aria-describedby={describedBy} required value={row.category_key ?? ""} onChange={(e) => update(index, { category_key: e.target.value })}><option value="">明确选择类别</option>{categories.map((category) => <option key={category.key} value={category.key}>{category.name}</option>)}</select></label>}
        <label>比较<select aria-describedby={describedBy} value={row.operator} onChange={(e) => update(index, { operator: e.target.value as Condition["operator"] })}>{Object.entries(operatorNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label>阈值（{definition?.unit ?? "数值"}）<input aria-describedby={describedBy} required type="number" step="any" value={row.threshold} onChange={(e) => update(index, { threshold: e.target.value })} /></label>
        <button type="button" aria-label={`删除${title}条件${index + 1}`} disabled={group.conditions.length === 1} onClick={() => { setHelpIndex(undefined); onChange({ ...group, conditions: group.conditions.filter((_, i) => i !== index) }); }}>删除</button>
        {help && <button type="button" className="journey-help-toggle" aria-expanded={helpOpen} aria-controls={helpOpen ? helpId : undefined} onClick={() => setHelpIndex(helpOpen ? undefined : index)}>{helpOpen ? "收起指标说明" : "指标说明"}</button>}</div>
        <p className="muted">{definition?.description}</p>
        {available && <p className={`journey-coverage ${available.status === "unavailable" ? "danger-text" : "muted"}`}>{coverageNames[available.status] ?? available.status} · {available.first_date ?? "无覆盖"}—{available.last_date ?? "无覆盖"}{available.reason ? ` · ${available.reason}` : ""}</p>}
        {helpOpen && help && <section className="journey-indicator-help" id={helpId} aria-labelledby={`${helpId}-title`}>
          <h3 id={`${helpId}-title`}>{definition?.label} · 指标说明</h3>
          <dl>
            <div><dt>投资含义</dt><dd id={`${helpId}-meaning`}>{help.meaning}</dd></div>
            <div><dt>如何理解</dt><dd>{help.interpretation}</dd></div>
            <div><dt>计算方式</dt><dd>{help.calculation}</dd></div>
            <div><dt>数据来源与口径</dt><dd>{help.source}</dd></div>
            <div><dt>使用边界</dt><dd>{help.caveat}</dd></div>
          </dl>
        </section>}
      </div>;
    })}
    <div className="journey-actions"><button type="button" onClick={() => onChange({ ...group, conditions: [...group.conditions, { indicator: "momentum", window: 20, operator: "gt", threshold: "0" }] })}>添加条件</button><button type="button" aria-expanded={more} onClick={() => setMore(!more)}>{more ? "收起更多指标" : "更多指标：波动、估值、资金与情绪"}</button></div>
    {duplicate && <p className="notice warning">存在相同指标与窗口，可能与已有条件重复。</p>}
  </fieldset>;
}

export default function StrategyEditor({ code, theme, initial, onSaved }: { code: string; theme: string; initial?: SavedStrategy; onSaved: () => void }) {
  const [catalog, setCatalog] = useState<JourneyCatalog>();
  const [coverage, setCoverage] = useState<Coverage>();
  const [versions, setVersions] = useState<SavedStrategy[]>([]);
  const [draft, setDraft] = useState<Draft>(() => ({ name: initial?.name ?? "我的趋势策略", rule: initial?.rule ?? trendRule(), settings: initial?.settings ?? { instrument_code: code, start_date: dateAgo(365), end_date: dateAgo(1), initial_cash: "50000", commission_rate: "0.0001", minimum_commission: "0", slippage_bps: "5" }, ...(initial ? { strategy_id: initial.strategy_id } : {}) }));
  const [selected, setSelected] = useState<number[]>([]);
  const [result, setResult] = useState<Comparison>();
  const [resultConfig, setResultConfig] = useState("");
  const [saved, setSaved] = useState<SavedStrategy>();
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [draftReady, setDraftReady] = useState(false);
  const [replace, setReplace] = useState(false);
  const [history, setHistory] = useState<Comparison[]>([]);
  const generation = useRef(0);
  const key = `etf-strategy-draft:${code}:${initial?.id ?? "new"}`;
  const signature = JSON.stringify({ draft, selected });
  const stale = !!result && resultConfig !== signature;
  useEffect(() => {
    const controller = new AbortController();
    let local: Draft | undefined;
    try { const raw = localStorage.getItem(key); if (raw) { const parsed = JSON.parse(raw) as Draft; if (parsed.settings?.instrument_code === code && parsed.rule?.buy?.conditions?.length && parsed.rule?.sell?.conditions?.length && (!parsed.strategy_id || parsed.strategy_id === initial?.strategy_id)) local = parsed; } } catch { /* 本地草稿损坏时继续读取服务端。 */ }
    Promise.all([
      api<JourneyCatalog>("/strategies/catalog", "GET", undefined, controller.signal),
      api<Coverage>(`/strategies/coverage?instrument_code=${code}`, "GET", undefined, controller.signal),
      api<SavedStrategy[]>(`/strategies?instrument_code=${code}`, "GET", undefined, controller.signal),
      api<Comparison[]>(`/strategies/comparisons?instrument_code=${code}`, "GET", undefined, controller.signal),
    ]).then(async ([data, ranges, items, runs]) => {
      if (controller.signal.aborted) return;
      setCatalog(data); setCoverage(ranges); setVersions(items); setHistory(runs);
      const instrument = data.instruments.find((row) => row.instrument_code === code);
      if (local) { setDraft(local); setDraftReady(true); }
      else if (!initial) {
        try {
          const stored = await api<Draft | null>(`/strategies/drafts/${code}`, "GET", undefined, controller.signal);
          if (controller.signal.aborted) return;
          if (stored && !stored.strategy_id) { setDraft(stored); setDraftReady(true); return; }
        } catch (e) { if (controller.signal.aborted) return; setDraftStatus(`未读取到服务端草稿，暂停自动保存以免覆盖：${(e as Error).message}`); return; }
        setDraft((old) => ({ ...old, settings: { ...old.settings, end_date: instrument?.last_date ?? old.settings.end_date, start_date: instrument?.default_start ?? old.settings.start_date } }));
        setDraftReady(true);
      } else setDraftReady(true);
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); generation.current += 1; };
  }, [code, initial?.id, key]);
  useEffect(() => {
    if (loading || !draftReady) return;
    try { localStorage.setItem(key, JSON.stringify(draft)); } catch { setDraftStatus("浏览器草稿保存失败，正在尝试服务端保存。"); }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api(`/strategies/drafts/${code}`, "PUT", draft, controller.signal)
        .then(() => { if (!controller.signal.aborted) setDraftStatus("草稿已保存，可稍后继续编辑"); })
        .catch((e) => { if (!controller.signal.aborted) setDraftStatus(`服务端草稿未保存：${e.message}；本机草稿仍保留。`); });
    }, 700);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [code, draft, key, loading, draftReady]);
  const updateRule = (rule: Rule) => { generation.current += 1; setDraft((old) => ({ ...old, rule })); setSaved(undefined); };
  const updateSettings = (field: keyof Draft["settings"], value: string) => { generation.current += 1; setDraft((old) => ({ ...old, settings: { ...old.settings, [field]: value } })); setSaved(undefined); };
  function template(value: string) {
    const rule = trendRule();
    if (value === "momentum") rule.buy.conditions.push({ indicator: "momentum", window: 20, operator: "gt", threshold: "0" });
    updateRule(rule);
  }
  async function compare() {
    const token = ++generation.current;
    setBusy(true); setError(""); setNotice(""); setSaved(undefined);
    try {
      const value = await api<Comparison>("/strategies/comparisons", "POST", { ...draft.settings, instrument_code: code, current: { name: draft.name, rule: draft.rule }, version_ids: selected });
      if (token !== generation.current) return;
      setResult(value); setResultConfig(signature); setHistory((old) => [value, ...old]);
    } catch (e) { if (token === generation.current) setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function save(enable: boolean) {
    if (!result || stale) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const value = saved ?? await api<SavedStrategy>("/strategies", "POST", { name: draft.name, instrument_code: code, comparison_id: result.id, track_key: "current", ...(draft.strategy_id ? { strategy_id: draft.strategy_id } : {}) });
      setSaved(value);
      if (enable) {
        const enabled = await api<SavedStrategy>(`/strategies/${value.id}/enable`, "POST", { replace_active: replace });
        setSaved(enabled);
        const positions = await api<AccountHoldings>("/account/holdings").catch(() => undefined);
        setNotice(`策略已启用。${activationMessage(enabled, positions)}`);
      } else setNotice(`已保存“${value.name}”第 ${value.version} 版，可继续与其他策略比较。`);
      onSaved();
      setVersions(await api<SavedStrategy[]>(`/strategies?instrument_code=${code}`));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function restore(id: number) {
    setBusy(true); setError("");
    try { const value = await api<Comparison>(`/strategies/comparisons/${id}`); setResult(value); setResultConfig(""); setSaved(undefined); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (loading) return <div className="empty" role="status">正在准备策略编辑器与数据覆盖…</div>;
  const active = versions.find((row) => row.active);
  const success = result?.tracks.some((row) => row.key === "current" && row.account);
  const usedConditions = [draft.rule, ...versions.filter((row) => selected.includes(row.id)).map((row) => row.rule)].flatMap((rule) => [...rule.buy.conditions, ...rule.sell.conditions]);
  const ranges = coverage?.conditions.filter((row) => usedConditions.some((condition) => condition.indicator === row.key)) ?? [];
  const firstDate = ranges.map((row) => row.first_date).filter((value): value is string => !!value).sort().at(-1);
  const lastDate = ranges.map((row) => row.last_date).filter((value): value is string => !!value).sort()[0];
  const warmup = Math.max(1, ...usedConditions.map((row) => (row.window ?? 0) + (row.indicator === "momentum" || row.indicator === "volatility" ? 1 : 0)));
  return <div className="journey-editor">
    <header className="journey-section-heading"><div><h1>{initial ? "修改策略 · 保存为新版" : "为这只 ETF 创建策略"}</h1><p className="muted mono">{code} · {catalog?.instruments.find((row) => row.instrument_code === code)?.instrument_name} · 仅供研究</p></div><a href={journeyUrl("etfs", code)}>查看真实操作与数据</a></header>
    <ol className="journey-steps"><li>了解操作</li><li aria-current="step">配置规则</li><li>回测比较</li><li>保存启用</li><li>每天看信号</li></ol>
    {error && <p className="alert" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}
    {!catalog ? <div className="empty">策略资料暂不可用。<button onClick={() => location.reload()}>重试</button></div> : <form onSubmit={(e) => { e.preventDefault(); void compare(); }}>
      <section className="panel journey-inset"><div className="journey-actions"><label>策略名称<input required maxLength={80} value={draft.name} disabled={busy} onChange={(e) => { generation.current += 1; setDraft({ ...draft, name: e.target.value }); setSaved(undefined); }} /></label><label>从模板开始<select defaultValue="" disabled={busy} onChange={(e) => template(e.target.value)}><option value="" disabled>选择可修改的起点</option><option value="trend">顺着趋势交易</option><option value="momentum">趋势加上涨确认</option><option value="custom">自己设置（从基础条件修改）</option></select></label></div><p className="muted">模板只是研究起点，不代表已找到最佳参数。{draftStatus}</p></section>
      <ConditionCard title="什么时候买" group={draft.rule.buy} definitions={catalog.conditions} categories={catalog.sentiment_categories} coverage={coverage} disabled={busy} onChange={(buy) => updateRule({ ...draft.rule, buy })} />
      <ConditionCard title="什么时候卖" group={draft.rule.sell} definitions={catalog.conditions} categories={catalog.sentiment_categories} coverage={coverage} disabled={busy} onChange={(sell) => updateRule({ ...draft.rule, sell })} />
      <fieldset className="journey-rule-card" disabled={busy}><legend>投入多少</legend><div className="journey-actions"><label>初始研究资金（元）<input type="number" required min={1000} max={100000000} step="0.01" value={draft.settings.initial_cash} onChange={(e) => updateSettings("initial_cash", e.target.value)} /></label><label>参与交易的比例<select value={draft.rule.allocation} onChange={(e) => updateRule({ ...draft.rule, allocation: Number(e.target.value) as 50 | 100 })}><option value={100}>全部资金</option><option value={50}>一半资金，另一半保留现金</option></select></label></div><p className="muted">研究本金不是实际账户现金；保留现金不补仓，持仓期间不每日调份额。</p></fieldset>
      <section className="panel journey-inset"><h2>这条策略会怎样操作</h2><p>{ruleSummary(draft.rule, catalog.conditions, catalog.sentiment_categories)}</p><p className="muted">买入确认不满足，不自动等于卖出；空仓时买卖条件同时成立则保持空仓。</p></section>
      <section className="panel journey-inset"><h2>回测并比较</h2><div className="journey-actions"><label>开始日期<input required type="date" value={draft.settings.start_date} onChange={(e) => updateSettings("start_date", e.target.value)} disabled={busy} /></label><label>截止日期<input required type="date" max={dateAgo(1)} value={draft.settings.end_date} onChange={(e) => updateSettings("end_date", e.target.value)} disabled={busy} /></label></div><p className="muted">选择另一段时间可检验不同市场阶段；看过的区间不再属于未见样本。所有策略统一比较条件，各自预热要求仍须满足。</p>
        <p className="notice">所选条件原始共同覆盖：{ranges.some((row) => row.status === "unavailable") || !firstDate || !lastDate || firstDate > lastDate ? "尚无完整共同覆盖，请先检查数据" : `${firstDate} 至 ${lastDate}`}；最长预热需求 {warmup} 个收盘点。开始日前须有完整预热数据，系统逐日校验，不自动缩短区间。</p>
        <details><summary>交易假设与成本</summary><div className="journey-actions"><label>佣金率<input required type="number" min="0" max="0.01" step="0.00001" value={draft.settings.commission_rate} onChange={(e) => updateSettings("commission_rate", e.target.value)} disabled={busy} /></label><label>最低佣金（元）<input required type="number" min="0" max="100" step="0.01" value={draft.settings.minimum_commission} onChange={(e) => updateSettings("minimum_commission", e.target.value)} disabled={busy} /></label><label>不利滑点（基点）<input required type="number" min="0" max="100" step="0.1" value={draft.settings.slippage_bps} onChange={(e) => updateSettings("slippage_bps", e.target.value)} disabled={busy} /></label></div><p className="muted">统一使用次交易日开盘、100份整手及分红权益核算，期末按收盘估值。未模拟盘口与真实撮合，低佣金不等于零成本。</p></details>
        <fieldset className="journey-version-picker" disabled={busy}><legend>加入其他策略 · 同一只 ETF</legend>{versions.length ? versions.map((row) => <label key={row.id}><input type="checkbox" checked={selected.includes(row.id)} onChange={(e) => { generation.current += 1; setSelected((old) => e.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id)); setSaved(undefined); }} />{row.name} · 第 {row.version} 版{row.active ? " · 正在运行" : ""}</label>) : <p className="muted">尚无其他已保存策略，先与一直持有比较；保存后可加入其他方法。</p>}</fieldset>
        <button className="primary" disabled={busy || !draft.name.trim()}>{busy ? "处理中…" : "回测这个策略并比较"}</button>
      </section>
    </form>}
    {result && <>{stale && <p className="notice warning">当前展示的是上次配置或历史比较结果。请重新回测当前配置后保存与启用。</p>}<StrategyComparison key={result.id} result={result} theme={theme} /><section className="panel journey-inset"><h2>决定保存还是开始运行</h2><p>收益与回撤分别判断，由你决定是否采用。保存只保留方法，启用才开始生成每日信号。</p>{active && <label className="journey-confirmations"><input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} disabled={busy} />我确认：启用新版将暂停“{active.name}”第 {active.version} 版，历史仍保留。</label>}<div className="journey-actions"><button disabled={busy || stale || !success} onClick={() => void save(false)}>保存策略</button><button className="primary" disabled={busy || stale || !success || (!!active && !replace)} onClick={() => void save(true)}>保存并启用</button><a href={journeyUrl("strategies", code)}>查看我的策略与信号</a></div></section></>}
    <details className="panel journey-inset"><summary>这只 ETF 的比较记录（{history.length}）</summary><div className="journey-history">{history.map((row) => <button disabled={busy} key={row.id} onClick={() => void restore(row.id)}>比较 #{row.id} · {row.settings.start_date}—{row.settings.end_date}</button>)}{!history.length && <p className="muted">尚无比较记录</p>}</div></details>
  </div>;
}
