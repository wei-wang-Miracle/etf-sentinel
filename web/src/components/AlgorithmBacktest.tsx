import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, stamp } from "../lib/api";
import { dateAgo } from "../lib/research";
import {
  evidenceForStrategy,
  evidenceTierLabel,
  isStrategyAdoptable,
  journeyUrl,
  strategyScopeLabel,
  type Comparison,
  type ComparisonTrack,
  type JourneyCatalog,
  type StrategyAssignment,
} from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import AppLink from "./AppLink";
import StrategyComparison from "./StrategyComparison";

type Props = {
  catalog: JourneyCatalog;
  code: string;
  algorithm: string;
  range: { start: string; end: string };
  theme: string;
  onCode: (code: string) => void;
  onAdopted: () => void;
};

export default function AlgorithmBacktest({ catalog, code, algorithm, range, theme, onCode, onAdopted }: Props) {
  const instrument = catalog.instruments.find((item) => item.instrument_code === code);
  const available = catalog.strategies.filter((item) => item.supported_instruments.includes(code));
  const initialTemplate = available.find((item) => item.id === algorithm);
  const yesterday = dateAgo(1);
  const maxDate = instrument?.default_end ?? yesterday;
  const initialTemplateStart = code ? initialTemplate?.earliest_start_by_instrument?.[code] : undefined;
  const defaultStart = range.start || (
    initialTemplateStart && (!instrument?.default_start || initialTemplateStart > instrument.default_start)
      ? initialTemplateStart
      : instrument?.default_start || ""
  );
  const [start, setStart] = useState(defaultStart);
  const [end, setEnd] = useState(range.end || instrument?.default_end || "");
  function isWarmupBlocked(item: (typeof available)[number], currentStart: string) {
    if (!code || !item.earliest_start_by_instrument) return false;
    const earliest = item.earliest_start_by_instrument[code];
    if (earliest === null) return true;
    return !!earliest && !!currentStart && currentStart < earliest;
  }
  const [selected, setSelected] = useState(() =>
    initialTemplate
      ? [initialTemplate.id]
      : available.filter((item) => !isWarmupBlocked(item, defaultStart)).map((item) => item.id),
  );
  const choices = available.filter((item) => selected.includes(item.id) && !isWarmupBlocked(item, start));
  const blockedWithStart = available.filter((item) => {
    const earliest = code ? item.earliest_start_by_instrument?.[code] : undefined;
    return !!earliest && !!start && start < earliest;
  });
  const latestWarmupStart = blockedWithStart.reduce(
    (latest, item) => {
      const earliest = code ? item.earliest_start_by_instrument?.[code] ?? "" : "";
      return earliest > latest ? earliest : latest;
    },
    "",
  );
  const signature = JSON.stringify([code, start, end, choices.map((item) => item.id)]);
  const [current, setCurrent] = useState<{ signature: string; result: Comparison }>();
  const [historicalId, setHistoricalId] = useState<number>();
  const [adopted, setAdopted] = useState<StrategyAssignment>();
  const [pending, setPending] = useState<ComparisonTrack>();
  const assignment = adopted ?? catalog.assignments.find((row) => row.instrument_code === code);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState<string>();
  const [error, setError] = useState("");
  const confirmRef = useRef<HTMLElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const history = useApiResource<Comparison[]>(code ? `/strategies/comparisons?instrument_code=${code}` : null);
  const historical = useApiResource<Comparison>(historicalId ? `/strategies/comparisons/${historicalId}` : null);
  const result = historicalId ? historical.data : current?.result;
  const stale = !historicalId && !!current && current.signature !== signature;
  const ready = !!instrument?.default_start && !!start && !!end && start <= end && end <= maxDate && choices.length > 0;

  useEffect(() => {
    if (pending) {
      confirmRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      confirmRef.current?.focus({ preventScroll: true });
    }
  }, [pending]);

  useEffect(() => {
    if (historicalId && historical.data) {
      resultRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [historicalId, historical.data]);

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy || saving) return;
    setBusy(true);
    setError("");
    try {
      const value = await api<Comparison>("/strategies/comparisons", "POST", {
        instrument_code: code, start_date: start, end_date: end,
        strategies: choices.map(({ id }) => id),
      });
      setCurrent({ result: value, signature });
      setHistoricalId(undefined);
      setPending(undefined);
      history.retry();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function adopt() {
    if (!result || !pending || historicalId || stale || busy || saving) return;
    setSaving(pending.key);
    setError("");
    try {
      const value = await api<StrategyAssignment>("/strategies/adopt", "POST", {
        comparison_id: result.id, strategy_id: pending.strategy_id,
        replace_active: !!assignment && assignment.strategy_id !== pending.strategy_id,
      });
      setAdopted(value);
      setPending(undefined);
      onAdopted();
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(undefined); }
  }

  return <div className="algorithm-research">
    <section className="panel journey-inset" aria-label="选择回测范围">
      <form onSubmit={(event) => void run(event)}>
        <div className="journey-actions algorithm-range">
          <label>回测 ETF <select aria-label="回测 ETF" value={code} disabled={busy || !!saving} onChange={(event) => onCode(event.target.value)}>
            <option value="">选择 ETF</option>
            {catalog.instruments.map((item) => <option key={item.instrument_code} value={item.instrument_code}>{item.instrument_code} · {item.instrument_name}{item.research_category ? `（${item.research_category}）` : ""}</option>)}
          </select></label>
          <label>开始日期 <input type="date" value={start} required max={end || maxDate} disabled={!code || busy || !!saving} onChange={(event) => setStart(event.target.value)} /></label>
          <label>结束日期 <input type="date" value={end} required min={start || undefined} max={maxDate} disabled={!code || busy || !!saving} onChange={(event) => setEnd(event.target.value)} /></label>
        </div>
        {!code ? <p className="muted">先选择 ETF，再比较算法。</p> : !instrument?.default_start ? <p className="notice warning">{instrument?.source_checked_through ? "这只 ETF 在可用权益区间内的日行情不足，暂不能完成预热。" : "这只 ETF 尚无已核验权益资料。请在数据管理更新权益资料后重试。"}</p> : null}
        {code && instrument?.research_category && <p className="muted">当前分类：<span className="mono">{instrument.research_category}</span> · 仅展示通用策略及该分类研究绑定策略。</p>}
        {instrument?.default_end && instrument.last_date && instrument.default_end < instrument.last_date && <p className="muted">当前可用数据截至 <span className="mono">{instrument.default_end}</span>；之后的行情尚未完成权益核验或不属于完整历史交易日。</p>}
        {start && end && (start > end || end > maxDate) && <p className="notice warning">请检查起止日期，结束日期不能晚于 <span className="mono">{maxDate}</span>。</p>}
        {!!latestWarmupStart && latestWarmupStart <= maxDate && <p className="notice">
          当前开始日期 <span className="mono">{start}</span> 早于「{blockedWithStart.map((item) => item.name).join("、")}」的预热要求，系统已自动避开未预热策略；如需全部参与，请
          <button type="button" onClick={() => {
            setStart(latestWarmupStart);
            setSelected((values) => Array.from(new Set([...values, ...blockedWithStart.map((item) => item.id)])));
          }}>调至 <span className="mono">{latestWarmupStart}</span> 以启用全部</button>
        </p>}
        {!!available.length && <fieldset className="algorithm-pick" disabled={busy || !!saving}>
          <legend>选择参加比较的算法</legend>
          {available.map((item) => {
            const earliest = code ? item.earliest_start_by_instrument?.[code] : undefined;
            const blocked = isWarmupBlocked(item, start);
            const adoptable = isStrategyAdoptable(item, code);
            const evidence = evidenceForStrategy(item, instrument?.research_category);
            return <div key={item.id} className="algorithm-pick-entry">
              <label className="algorithm-option">
                <input type="checkbox" disabled={blocked} checked={!blocked && selected.includes(item.id)} onChange={(event) => setSelected((values) => event.target.checked ? [...values, item.id] : values.filter((value) => value !== item.id))} />
                <span>
                  <strong>{item.name}{!adoptable ? "（仅比较观察）" : ""}</strong>
                  <span className="muted">
                    {strategyScopeLabel(item)}
                    {evidence ? ` · ${evidenceTierLabel(evidence)}` : ""}
                    {blocked ? (earliest === null ? ` · 行情总量不足 ${item.min_warmup_bars ?? 250} 日预热` : ` · 需 ${earliest} 起（${item.min_warmup_bars ?? 250} 日预热）`) : ""}
                    {" · "}
                    {item.description}
                  </span>
                </span>
              </label>
              {blocked && earliest && earliest <= maxDate && <button type="button" onClick={() => {
                setStart(earliest);
                setSelected((values) => values.includes(item.id) ? values : [...values, item.id]);
              }}>调至 {earliest}</button>}
              <AppLink href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id, from: "backtest", ...(start ? { start } : {}), ...(end ? { end } : {}) })}>算法说明</AppLink>
            </div>;
          })}
        </fieldset>}
        {!!available.length && !choices.length && <p className="notice warning">请至少选择一套算法后再运行回测。</p>}
        <div className="journey-section-heading algorithm-run">
          <p className="muted">统一口径：¥50,000 本金 · 佣金万一 · 滑点 5bp · 次日开盘成交</p>
          <button className="primary" type="submit" disabled={busy || !!saving || !ready}>{busy ? "正在计算…" : "运行回测"}</button>
        </div>
      </form>
    </section>
    {error && <p className="notice warning" role="alert">{error}</p>}
    {busy && <p className="notice" role="status">正在按同一份行情计算各算法和持有参照…</p>}
    {stale && <p className="notice" role="status">研究范围已变更，请重新运行后再采用。</p>}
    {historical.loading && <p className="notice" role="status">正在读取回测快照…</p>}
    {historical.error && <p className="notice warning" role="alert">{historical.error} <button onClick={historical.retry}>重试</button></p>}
    {pending && !historicalId && !stale && <section ref={confirmRef} tabIndex={-1} className="notice" aria-label="确认采用策略">
      <p>{assignment && assignment.strategy_id !== pending.strategy_id ? "替换当前策略为" : "采用"}「{pending.name}」用于 <span className="mono">{code}</span> 的后续盘前信号（保留历史计划）。</p>
      <div className="journey-actions"><button className="primary" disabled={!!saving} onClick={() => void adopt()}>确认采用</button><button disabled={!!saving} onClick={() => setPending(undefined)}>取消</button></div>
    </section>}
    <div ref={resultRef}>
      {result && <StrategyComparison key={result.id} result={result} theme={theme} renderAdoption={!stale && !historicalId ? (track) => {
        if (track.strategy_id === "hold" || !track.account || track.status !== "success") return <span className="muted">—</span>;
        const definition = catalog.strategies.find((item) => item.id === track.strategy_id);
        if (!isStrategyAdoptable(definition, code)) return <span className="muted">仅比较观察</span>;
        if (assignment?.active && assignment.strategy_id === track.strategy_id) return <AppLink href={journeyUrl("etfs", code, { detail: "signals" })}>当前已采用 · 查看信号</AppLink>;
        return <button type="button" disabled={busy || !!saving} aria-label={`采用${track.name}`} onClick={() => setPending(track)}>采用策略</button>;
      } : undefined} />}
    </div>
    {code && <details className="panel journey-inset">
      <summary>历史回测</summary>
      {history.loading && <p role="status">正在读取回测记录…</p>}
      {history.error && <p role="alert">{history.error} <button onClick={history.retry}>重试</button></p>}
      {history.data?.length === 0 && <p className="muted">这只 ETF 暂无回测记录。</p>}
      {history.data?.map((row) => <div className="journey-saved-row" key={row.id}>
        <span className="mono">{row.settings.start_date} 至 {row.settings.end_date} · {stamp(row.created_at)}</span>
        <button disabled={busy || !!saving} aria-pressed={row.id === result?.id} onClick={() => setHistoricalId(row.id)}>查看回测 #{row.id}</button>
      </div>)}
      {historicalId && <button disabled={busy || !!saving} onClick={() => setHistoricalId(undefined)}>返回本次回测</button>}
    </details>}
  </div>;
}
