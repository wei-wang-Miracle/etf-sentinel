import { ruleSummary, type Comparison, type JourneyCatalog, type SavedStrategy } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import StrategyComparison from "./StrategyComparison";

export default function StrategyVersion({ version, catalog, theme, onCompare, onEdit }: {
  version: SavedStrategy; catalog?: JourneyCatalog; theme: string; onCompare: () => void; onEdit: () => void;
}) {
  const snapshot = useApiResource<Comparison>(version.comparison_id ? `/strategies/comparisons/${version.comparison_id}` : null);
  const result = snapshot.data;
  const matches = result?.instrument_code === version.instrument_code && result.tracks.some((row) => row.backtest_id === version.backtest_id);
  return <>
    <section className="panel journey-inset">
      <h2>{version.name} · 第 {version.version} 版</h2><p>已保存版本 · 只读</p>
      <p>{ruleSummary(version.rule, catalog?.conditions ?? [], catalog?.sentiment_categories ?? [])}</p>
      <p>研究区间 {version.settings.start_date}—{version.settings.end_date} · 本金 {version.settings.initial_cash} 元</p>
      <div className="journey-actions"><button className="primary" onClick={onCompare}>回测与比较此版本</button><button onClick={onEdit}>基于此版本修改</button></div>
    </section>
    <section aria-label="保存时的回测">
      <h2>保存时的回测 · 只读快照</h2><p className="muted">以下为保存版本时的冻结结果。重新比较可调整研究假设，不改变原版本或启用状态。</p>
      {snapshot.loading ? <p role="status">正在读取保存时的回测…</p> : snapshot.error ? <p className="alert" role="alert">回测读取失败：{snapshot.error}<button onClick={snapshot.retry}>重试回测</button></p>
        : result && matches ? <StrategyComparison key={result.id} result={result} theme={theme} initialBacktestId={version.backtest_id} />
          : <p className="notice warning">{result ? "回测快照与当前版本不匹配。" : "此版本暂无关联的比较快照。"}仍可通过“回测与比较此版本”重新研究。</p>}
    </section>
  </>;
}
