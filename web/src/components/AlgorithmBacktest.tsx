import { useState, type FormEvent } from "react";
import { api, stamp } from "../lib/api";
import { dateAgo } from "../lib/research";
import { journeyUrl, templateKey, type Comparison, type JourneyCatalog, type SavedStrategy } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import StrategyComparison from "./StrategyComparison";

type Props = {
  catalog: JourneyCatalog;
  code: string;
  algorithm: string;
  range: { start: string; end: string };
  theme: string;
  onCode: (code: string) => void;
  onSaved: (value: SavedStrategy) => void;
};

export default function AlgorithmBacktest({ catalog, code, algorithm, range, theme, onCode, onSaved }: Props) {
  const instrument = catalog.instruments.find((item) => item.instrument_code === code);
  const available = catalog.templates.filter((item) => item.supported_instruments.includes(code));
  const initialTemplate = available.find((item) => item.id === algorithm || templateKey(item) === algorithm);
  const yesterday = dateAgo(1);
  const maxDate = instrument?.default_end ?? yesterday;
  const [start, setStart] = useState(range.start || instrument?.default_start || "");
  const [end, setEnd] = useState(range.end || instrument?.default_end || "");
  const [selected, setSelected] = useState(() => initialTemplate ? [initialTemplate.id] : available.map((item) => item.id));
  const choices = available.filter((item) => selected.includes(item.id));
  const signature = JSON.stringify([code, start, end, choices.map(templateKey)]);
  const [current, setCurrent] = useState<{ signature: string; result: Comparison }>();
  const [historicalId, setHistoricalId] = useState<number>();
  const [saved, setSaved] = useState<Record<string, SavedStrategy>>({});
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState<string>();
  const [error, setError] = useState("");
  const history = useApiResource<Comparison[]>(code ? `/strategies/comparisons?instrument_code=${code}` : null);
  const historical = useApiResource<Comparison>(historicalId ? `/strategies/comparisons/${historicalId}` : null);
  const result = historicalId ? historical.data : current?.result;
  const stale = !historicalId && !!current && current.signature !== signature;
  const ready = !!instrument?.default_start && !!start && !!end && start <= end && end <= maxDate && choices.length > 0;

  async function run(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy || saving) return;
    setBusy(true);
    setError("");
    try {
      const value = await api<Comparison>("/strategies/comparisons", "POST", {
        instrument_code: code, start_date: start, end_date: end,
        templates: choices.map(({ id, version }) => ({ id, version })),
      });
      setCurrent({ result: value, signature });
      setHistoricalId(undefined);
      setSaved({});
      history.retry();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function save(trackKey: string) {
    if (!result || stale || busy || saving) return;
    setSaving(trackKey);
    setError("");
    try {
      const value = await api<SavedStrategy>("/strategies", "POST", { comparison_id: result.id, track_key: trackKey });
      setSaved((items) => ({ ...items, [`${result.id}:${trackKey}`]: value }));
      onSaved(value);
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(undefined); }
  }

  return <div className="algorithm-research">
    <section className="panel journey-inset" aria-label="选择回测范围">
      <form onSubmit={(event) => void run(event)}>
        <div className="journey-actions algorithm-range">
          <label>回测 ETF <select aria-label="回测 ETF" value={code} disabled={busy || !!saving} onChange={(event) => onCode(event.target.value)}>
            <option value="">选择 ETF</option>
            {catalog.instruments.map((item) => <option key={item.instrument_code} value={item.instrument_code}>{item.instrument_code} · {item.instrument_name}</option>)}
          </select></label>
          <label>开始日期 <input type="date" value={start} required max={end || maxDate} disabled={!code || busy || !!saving} onChange={(event) => setStart(event.target.value)} /></label>
          <label>结束日期 <input type="date" value={end} required min={start || undefined} max={maxDate} disabled={!code || busy || !!saving} onChange={(event) => setEnd(event.target.value)} /></label>
        </div>
        {!code ? <p className="muted">先选择 ETF，再比较算法。</p> : !instrument?.default_start ? <p className="notice warning">{instrument?.source_checked_through ? "这只 ETF 在可用权益区间内的日行情不足，暂不能完成预热。" : "这只 ETF 尚无已核验权益资料。请在数据管理更新权益资料后重试。"}</p> : null}
        {instrument?.default_end && instrument.last_date && instrument.default_end < instrument.last_date && <p className="muted">当前可用数据截至 <span className="mono">{instrument.default_end}</span>；之后的行情尚未完成权益核验或不属于完整历史交易日。</p>}
        {start && end && (start > end || end > maxDate) && <p className="notice warning">请检查起止日期，结束日期不能晚于 <span className="mono">{maxDate}</span>。</p>}
        {!!available.length && <fieldset className="algorithm-pick" disabled={busy || !!saving}>
          <legend>选择参加比较的算法</legend>
          {available.map((item) => <div key={item.id} className="algorithm-pick-entry">
            <label className="algorithm-option">
              <input type="checkbox" checked={selected.includes(item.id)} onChange={(event) => setSelected((values) => event.target.checked ? [...values, item.id] : values.filter((value) => value !== item.id))} />
              <span><strong>{item.name}</strong><span className="muted">{item.description}</span></span>
            </label>
            <a href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id })}>算法说明</a>
          </div>)}
        </fieldset>}
        <div className="journey-section-heading algorithm-run">
          <p className="muted">统一口径：本金 ¥50,000，佣金万分之一，最低佣金 ¥0，滑点 5 基点。收盘判定，下一交易日开盘模拟成交。</p>
          <button className="primary" type="submit" disabled={busy || !!saving || !ready}>{busy ? "正在计算…" : "运行回测"}</button>
        </div>
      </form>
    </section>
    {error && <p className="notice warning" role="alert">{error}</p>}
    {busy && <p className="notice" role="status">正在按同一份行情计算各算法和持有参照…</p>}
    {stale && <p className="notice" role="status">研究范围已变更，请重新运行后再保存。</p>}
    {historical.loading && <p className="notice" role="status">正在读取回测快照…</p>}
    {historical.error && <p className="notice warning" role="alert">{historical.error} <button onClick={historical.retry}>重试</button></p>}
    {result && <StrategyComparison key={result.id} result={result} theme={theme} renderBinding={!stale ? (track) => {
      if (!track.template || !track.key.startsWith("template:") || !track.account || track.status !== "success") return <span className="muted">—</span>;
      const binding = saved[`${result.id}:${track.key}`];
      if (binding) return <><span role="status">已绑定 · {binding.active ? "已启用" : "未启用"}</span><br /><a href={journeyUrl("strategies", code, { view: "version", edit: String(binding.id) })} aria-label={`查看${track.name}绑定`}>查看绑定</a></>;
      return <button type="button" disabled={busy || !!saving} aria-label={`保存并绑定${track.name}`} onClick={() => void save(track.key)}>{saving === track.key ? "保存中…" : "保存并绑定"}</button>;
    } : undefined} />}
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
