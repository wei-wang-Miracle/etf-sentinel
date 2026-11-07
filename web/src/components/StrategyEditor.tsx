import { useEffect, useId, useRef, useState } from "react";
import { api } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { dateAgo, number, useResearchQuery } from "../lib/research";
import {
  activationMessage, journeyUrl, operatorNames, ruleSummary, trendRule,
  type Comparison, type Condition, type ConditionDefinition, type ConditionGroup,
  type Coverage, type Draft, type JourneyCatalog, type Rule, type SavedStrategy,
} from "../lib/strategyJourney";
import "../styles/strategy-journey.css";
import StrategyComparison from "./StrategyComparison";
import { strategyIndicatorHelp } from "../lib/strategyIndicatorHelp";

const coverageNames: Record<string, string> = { historical: "可用于历史回测", revised: "可做修订历史研究", unavailable: "当前不能使用" };

function ConditionCard({ title, group, definitions, categories, coverage, onChange, disabled }: {
  title: string; group: ConditionGroup; definitions: ConditionDefinition[];
  categories: JourneyCatalog["sentiment_categories"]; coverage?: Coverage;
  onChange: (group: ConditionGroup) => void; disabled: boolean;
}) {
  const [more, setMore] = useState(false);
  const [helpIndex, setHelpIndex] = useState<number>(0);
  const [explicitHelp, setExplicitHelp] = useState(false);
  const helpPrefix = useId();
  const update = (index: number, patch: Partial<Condition>) => onChange({ ...group, conditions: group.conditions.map((row, i) => i === index ? { ...row, ...patch } : row) });
  const duplicate = group.conditions.some((row, i) => group.conditions.some((other, j) => i !== j && row.indicator === other.indicator && row.window === other.window));
  return <fieldset className="journey-rule-card journey-conditions-card" disabled={disabled}>
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
          if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) { setHelpIndex(index); setExplicitHelp(false); }
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
        <button type="button" aria-label={`删除${title}条件${index + 1}`} disabled={group.conditions.length === 1} onClick={() => { setHelpIndex(0); onChange({ ...group, conditions: group.conditions.filter((_, i) => i !== index) }); }}>删除</button>
        {help && <button type="button" className="journey-help-toggle" aria-expanded={helpOpen && explicitHelp} aria-controls={helpOpen ? helpId : undefined} onClick={() => { setHelpIndex(index); setExplicitHelp(!explicitHelp); }}>{helpOpen && explicitHelp ? "收起指标说明" : "指标说明"}</button>}</div>
        <p className="muted">{definition?.description}</p>
        {available && <p className={`journey-coverage ${available.status === "unavailable" ? "danger-text" : "muted"}`}>{coverageNames[available.status] ?? available.status} · {available.first_date ?? "无覆盖"}—{available.last_date ?? "无覆盖"}{available.reason ? ` · ${available.reason}` : ""}</p>}
        {helpOpen && help && <section className={`journey-indicator-help ${explicitHelp ? "explicit-help" : ""}`} id={helpId} aria-labelledby={`${helpId}-title`}>
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
  const [query, updateQuery] = useResearchQuery({ stage: "rules" });
  const stage = ["rules", "compare", "save"].includes(query.stage) ? query.stage : "rules";
  const [requestedRange] = useState(() => {
    const params = new URLSearchParams(location.search);
    const start = params.get("start"), end = params.get("end");
    const valid = (value: string | null): value is string => !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
    return valid(start) && valid(end) && start <= end && end < dateAgo(0) ? { start_date: start, end_date: end } : undefined;
  });
  const [retainedDates, setRetainedDates] = useState(false);
  const [confirmEnable, setConfirmEnable] = useState(false);
  const [catalog, setCatalog] = useState<JourneyCatalog>();
  const [coverage, setCoverage] = useState<Coverage>();
  const [versions, setVersions] = useState<SavedStrategy[]>([]);
  const [draft, setDraft] = useState<Draft>(() => ({ name: initial?.name ?? "我的趋势策略", rule: initial?.rule ?? trendRule(), settings: initial?.settings ?? { instrument_code: code, start_date: dateAgo(365), end_date: dateAgo(1), initial_cash: "50000", commission_rate: "0.0001", minimum_commission: "0", slippage_bps: "5" }, ...(initial ? { strategy_id: initial.strategy_id } : {}) }));
  const [selected, setSelected] = useState<number[]>([]);
  const [result, setResult] = useState<Comparison>();
  const [historical, setHistorical] = useState<Comparison>();
  const [refreshError, setRefreshError] = useState("");
  const [resultConfig, setResultConfig] = useState("");
  const [saved, setSaved] = useState<SavedStrategy>();
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [draftStatus, setDraftStatus] = useState("");
  const [draftReady, setDraftReady] = useState(false);

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
      if (local) { setDraft(local); setRetainedDates(!!requestedRange); setDraftReady(true); }
      else if (!initial) {
        try {
          const stored = await api<Draft | null>(`/strategies/drafts/${code}`, "GET", undefined, controller.signal);
          if (controller.signal.aborted) return;
          if (stored && !stored.strategy_id) { setDraft(stored); setRetainedDates(!!requestedRange); setDraftReady(true); return; }
        } catch (e) { if (controller.signal.aborted) return; setDraftStatus(`未读取到服务端草稿，暂停自动保存以免覆盖：${(e as Error).message}`); return; }
        setDraft((old) => ({ ...old, settings: { ...old.settings, end_date: instrument?.last_date ?? old.settings.end_date, start_date: instrument?.default_start ?? old.settings.start_date, ...requestedRange } }));
        setDraftReady(true);
      } else { setRetainedDates(!!requestedRange); setDraftReady(true); }
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); generation.current += 1; };
  }, [code, initial?.id, key, requestedRange]);
  useEffect(() => {
    if (loading || !draftReady) return;
    let localSaved = false;
    try { localStorage.setItem(key, JSON.stringify(draft)); localSaved = true; setDraftStatus("本机草稿已保存，服务端保存中…"); } catch { setDraftStatus("本机草稿未保存，正在尝试服务端保存。"); }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api(`/strategies/drafts/${code}`, "PUT", draft, controller.signal)
        .then(() => { if (!controller.signal.aborted) setDraftStatus(localSaved ? "本机与服务端草稿已保存" : "服务端草稿已保存，本机未保存"); })
        .catch((e) => { if (!controller.signal.aborted) setDraftStatus(`服务端草稿未保存：${e.message}；${localSaved ? "本机草稿仍保留" : "本机草稿也未保存"}。`); });
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
    setBusy(true); setError(""); setNotice(""); setRefreshError("");
    let persisted = saved;
    try {
      const value = saved ?? await api<SavedStrategy>("/strategies", "POST", { name: draft.name, instrument_code: code, comparison_id: result.id, track_key: "current", ...(draft.strategy_id ? { strategy_id: draft.strategy_id } : {}) });
      persisted = value; setSaved(value);
      if (enable) {
        const enabled = await api<SavedStrategy>(`/strategies/${value.id}/enable`, "POST", { replace_active: true });
        setSaved(enabled);
        const positions = await api<AccountHoldings>("/account/holdings").catch(() => undefined);
        setConfirmEnable(false); setNotice(`策略已启用。${activationMessage(enabled, positions)}`);
      } else setNotice(`已保存“${value.name}”第 ${value.version} 版，可继续与其他策略比较。`);
    } catch (e) { setError(`${persisted && enable ? "版本已保存，启用未成功：" : ""}${(e as Error).message}`); return; }
    finally { setBusy(false); }
    onSaved();
    try { setVersions(await api<SavedStrategy[]>(`/strategies?instrument_code=${code}`)); }
    catch (e) { setRefreshError(`版本列表刷新失败，已保存或启用的结果不受影响：${(e as Error).message}`); }
  }
  async function restore(id: number) {
    setBusy(true); setError("");
    try { const value = await api<Comparison>(`/strategies/comparisons/${id}`); setHistorical(value); }
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
  if (historical) return <div className="journey-editor">
    <section className="panel journey-inset"><h2>历史比较 · 只读快照</h2><p>{historical.instrument_code} · {historical.settings.start_date}—{historical.settings.end_date} · 研究本金 {number(historical.settings.initial_cash)} 元</p><p>佣金率 {historical.settings.commission_rate}；最低佣金 {historical.settings.minimum_commission} 元；不利滑点 {historical.settings.slippage_bps} 基点。次交易日开盘模拟执行，100 份整手，期末按收盘估值。</p><p>以下使用当次冻结输入，核验不采用最新行情。当前草稿与当前比较结果均保留，不会被历史快照覆盖。</p>
      {historical.tracks.map((row) => <section key={row.key}><h3>{row.name} · 冻结规则</h3><p>{row.rule && catalog ? ruleSummary(row.rule, catalog.conditions, catalog.sentiment_categories) : row.key === "hold" || row.key === "hold_half" ? `持有参照；投入比例${row.allocation == null ? "未提供" : `${row.allocation}%`}，其余依据见当次模拟成交。` : "本次快照未提供条件规则，不能用当前草稿或后来版本代替。"}</p>{row.status !== "success" && <p className="notice warning">{row.reason ?? "本次未完成计算"}</p>}</section>)}
      <button className="primary" onClick={() => setHistorical(undefined)}>返回当前草稿</button>
    </section><StrategyComparison key={historical.id} result={historical} theme={theme} />
  </div>;
  return <div className="journey-editor">
    <header className="journey-section-heading"><div><h2>{initial ? "修改策略 · 保存为新版" : "为这只 ETF 创建策略"}</h2><p className="muted mono">{code} · {catalog?.instruments.find((row) => row.instrument_code === code)?.instrument_name} · 仅供研究</p></div><a href={journeyUrl("etfs", code)}>查看真实操作与数据</a></header>
    <ol className="journey-steps">{[["rules", "配置规则"], ["compare", "回测比较"], ["save", "保存与启用"]].map(([value, label]) => <li key={value} aria-current={stage === value ? "step" : undefined}><button disabled={busy || (value === "save" && (!result || stale))} onClick={() => updateQuery({ stage: value })}>{label}</button></li>)}</ol>
    {error && <p className="alert" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}{refreshError && <p className="notice warning">{refreshError}</p>}{retainedDates && <p className="notice">已保留草稿或版本的日期 {draft.settings.start_date}—{draft.settings.end_date}，未用研究链接的日期覆盖。可在回测比较中调整。</p>}
    {!catalog ? <div className="empty">策略资料暂不可用。<button onClick={() => location.reload()}>重试</button></div> : <form onSubmit={(e) => { e.preventDefault(); if (stage === "rules") updateQuery({ stage: "compare" }); else void compare(); }}>
      <div hidden={stage !== "rules"}>
      <section className="panel journey-inset"><div className="journey-actions"><label>策略名称<input required maxLength={80} value={draft.name} disabled={busy} onChange={(e) => { generation.current += 1; setDraft({ ...draft, name: e.target.value }); setSaved(undefined); }} /></label><label>从模板开始<select defaultValue="" disabled={busy} onChange={(e) => template(e.target.value)}><option value="" disabled>选择可修改的起点</option><option value="trend">顺着趋势交易</option><option value="momentum">趋势加上涨确认</option><option value="custom">自己设置（从基础条件修改）</option></select></label></div><p className="muted">模板只是研究起点，不代表已找到最佳参数。{draftStatus}</p></section>
      <ConditionCard title="什么时候买" group={draft.rule.buy} definitions={catalog.conditions} categories={catalog.sentiment_categories} coverage={coverage} disabled={busy} onChange={(buy) => updateRule({ ...draft.rule, buy })} />
      <ConditionCard title="什么时候卖" group={draft.rule.sell} definitions={catalog.conditions} categories={catalog.sentiment_categories} coverage={coverage} disabled={busy} onChange={(sell) => updateRule({ ...draft.rule, sell })} />
      <fieldset className="journey-rule-card" disabled={busy}><legend>投入多少</legend><div className="journey-actions"><label>参与交易的比例<select value={draft.rule.allocation} onChange={(e) => updateRule({ ...draft.rule, allocation: Number(e.target.value) as 50 | 100 })}><option value={100}>全部资金</option><option value={50}>一半资金，另一半保留现金</option></select></label></div><p className="muted">研究本金不是实际账户现金；保留现金不补仓，持仓期间不每日调份额。</p></fieldset>
      <section className="panel journey-inset"><h2>这条策略会怎样操作</h2><p>{ruleSummary(draft.rule, catalog.conditions, catalog.sentiment_categories)}</p><p className="muted">买入确认不满足，不自动等于卖出；空仓时买卖条件同时成立则保持空仓。</p></section>
      {coverage?.conditions.some((row) => row.status === "revised" && [...draft.rule.buy.conditions, ...draft.rule.sell.conditions].some((condition) => condition.indicator === row.key)) && <p className="notice warning">修订历史研究，未证明原时点可得。历史来源可能修订，不作为原时点已知信息。</p>}
      <button className="primary" disabled={busy}>下一步：回测比较</button></div>
      <div hidden={stage !== "compare"}><section className="panel journey-inset"><h2>回测并比较</h2><div className="journey-actions"><label>开始日期<input required type="date" value={draft.settings.start_date} onChange={(e) => updateSettings("start_date", e.target.value)} disabled={busy} /></label><label>截止日期<input required type="date" min={draft.settings.start_date} max={dateAgo(1)} value={draft.settings.end_date} onChange={(e) => updateSettings("end_date", e.target.value)} disabled={busy} /></label></div><p className="muted">选择另一段时间可检验不同市场阶段；看过的区间不再属于未见样本。所有策略统一比较条件，各自预热要求仍须满足。</p>
        <p className="notice">所选条件原始共同覆盖：{ranges.some((row) => row.status === "unavailable") || !firstDate || !lastDate || firstDate > lastDate ? "尚无完整共同覆盖，请先检查数据" : `${firstDate} 至 ${lastDate}`}；最长预热需求 {warmup} 个收盘点。开始日前须有完整预热数据，系统逐日校验，不自动缩短区间。</p>
        <div><h3>交易假设与成本</h3><label>初始研究资金（元）<input required type="number" min={1000} max={100000000} step="0.01" value={draft.settings.initial_cash} disabled={busy} onChange={(e) => updateSettings("initial_cash", e.target.value)} /></label><div className="journey-actions"><label>佣金率<input required type="number" min="0" max="0.01" step="0.00001" value={draft.settings.commission_rate} onChange={(e) => updateSettings("commission_rate", e.target.value)} disabled={busy} /></label><label>最低佣金（元）<input required type="number" min="0" max="100" step="0.01" value={draft.settings.minimum_commission} onChange={(e) => updateSettings("minimum_commission", e.target.value)} disabled={busy} /></label><label>不利滑点（基点）<input required type="number" min="0" max="100" step="0.1" value={draft.settings.slippage_bps} onChange={(e) => updateSettings("slippage_bps", e.target.value)} disabled={busy} /></label></div><p className="muted">统一使用次交易日开盘、100份整手及分红权益核算，期末按收盘估值。未模拟盘口与真实撮合，低佣金不等于零成本。</p></div>
        <fieldset className="journey-version-picker" disabled={busy}><legend>加入其他策略 · 同一只 ETF</legend>{versions.length ? versions.map((row) => <label key={row.id}><input type="checkbox" checked={selected.includes(row.id)} onChange={(e) => { generation.current += 1; setSelected((old) => e.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id)); setSaved(undefined); }} />{row.name} · 第 {row.version} 版{row.active ? " · 正在运行" : ""}</label>) : <p className="muted">尚无其他已保存策略，先与一直持有比较；保存后可加入其他方法。</p>}</fieldset>
        <button className={!result || stale ? "primary" : undefined} disabled={busy || !draft.name.trim()}>{busy ? "正在计算…" : "运行回测"}</button>
      </section></div>
    </form>}
    {stale && <p className="notice warning">结果对应上次配置。请重新运行回测，当前配置不能保存或启用。</p>}
    {result && stage === "compare" && <><StrategyComparison key={result.id} result={result} theme={theme} /><div className="journey-actions"><button disabled={busy} onClick={() => updateQuery({ stage: "rules" })}>返回修改规则</button><button className="primary" disabled={busy || stale || !success} onClick={() => updateQuery({ stage: "save" })}>继续：保存</button></div></>}
    {stage === "save" && <section className="panel journey-inset"><h2>保存与启用</h2><p>{code} · {draft.name} · {initial ? "保存为新版本" : "新版本"}</p><p>{catalog && ruleSummary(draft.rule, catalog.conditions, catalog.sentiment_categories)}</p><p>比较区间 {draft.settings.start_date}—{draft.settings.end_date}；研究本金 {draft.settings.initial_cash} 元。保存只保留方法，启用才开始准备每日信号。</p><p>当前启用：{active ? `${active.name} · 第 ${active.version} 版` : "尚未启用策略"}</p><div className="journey-actions">{saved?.active ? <a className="primary" href={journeyUrl("etfs", code, { detail: "signals" })}>查看每日信号</a> : <><button className="primary" disabled={busy || stale || !success || !!saved} onClick={() => void save(false)}>{saved ? "版本已保存" : "保存版本"}</button><button disabled={busy || stale || !success} onClick={() => setConfirmEnable(true)}>{saved ? "启用已保存版本…" : "保存并启用…"}</button></>}</div>
      {confirmEnable && <section className="notice" role="region" aria-label="确认启用策略"><h3>确认启用 {catalog?.instruments.find((row) => row.instrument_code === code)?.instrument_name} {code} · {draft.name}</h3><p>新版本：{saved ? `第 ${saved.version} 版` : "待保存的新版本"}。{active ? `将替换 ${active.name} 第 ${active.version} 版，保留历史。` : "这是首次启用。"}</p><p>下一适用日期和运行就绪状态待服务端核验。不补写历史，不自动下单；计划不等于成交。</p><button disabled={busy || stale} onClick={() => void save(true)}>确认启用</button><button disabled={busy} onClick={() => setConfirmEnable(false)}>取消</button></section>}
      {saved && <p role="status">已保存“{saved.name}”第 {saved.version} 版。{!saved.active && <><a href={journeyUrl("etfs", code, { detail: "signals" })}>查看每日信号</a> · </>}<a href={journeyUrl("strategies", code)}>返回版本列表</a></p>}
    </section>}

    <details className="panel journey-inset"><summary>这只 ETF 的比较记录（{history.length}）</summary><div className="journey-history">{history.map((row) => <button disabled={busy} key={row.id} onClick={() => void restore(row.id)}>比较 #{row.id} · {row.settings.start_date}—{row.settings.end_date}</button>)}{!history.length && <p className="muted">尚无比较记录</p>}</div></details>
  </div>;
}
