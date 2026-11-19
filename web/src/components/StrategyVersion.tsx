import type { ReactNode } from "react";
import { journeyUrl, type Comparison, type SavedStrategy } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import StrategyComparison from "./StrategyComparison";

export default function StrategyVersion({ version, theme, children }: {
  version: SavedStrategy; theme: string; children?: ReactNode;
}) {
  const snapshot = useApiResource<Comparison>(version.comparison_id ? `/strategies/comparisons/${version.comparison_id}` : null);
  const result = snapshot.data;
  const matches = result?.instrument_code === version.instrument_code && result.tracks.some((row) =>
    row.backtest_id === version.backtest_id && row.template?.id === version.template.id && row.template.version === version.template.version);
  return <>
    <section className="panel journey-inset">
      <h2>{version.name} · {version.instrument_code}</h2>
      <p>{version.active ? "已启用每日信号" : "未启用"}</p>
      <p>{version.template.name} · 共享算法</p>
      <p>研究区间 {version.settings.start_date}—{version.settings.end_date} · 本金 {version.settings.initial_cash} 元 · 模拟投入比例 100%</p>
      <p>{version.template.note}</p>
      <p className="muted">历史结果按保存时的内部规则快照核验；当前算法说明展示现行规则。</p>
      <a href={journeyUrl("strategies", version.instrument_code, { view: "algorithm", algorithm: version.template.id })}>查看当前算法说明</a>
    </section>
    {children}
    <section aria-label="保存时的回测">
      <h2>保存时的回测 · 只读快照</h2>
      <p className="muted">此结果保留保存时的内部规则、交易口径及行情快照。</p>
      {snapshot.loading ? <p role="status">正在读取保存时的回测…</p> : snapshot.error ? <p className="alert" role="alert">回测读取失败：{snapshot.error}<button onClick={snapshot.retry}>重试回测</button></p>
        : result && matches ? <StrategyComparison key={result.id} result={result} theme={theme} initialBacktestId={version.backtest_id} />
          : <p className="notice warning">{result ? "历史回测快照与此绑定的内部规则记录不匹配。" : "此绑定暂无关联的比较快照。"}</p>}
    </section>
  </>;
}
