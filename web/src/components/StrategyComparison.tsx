import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Candle } from "../lib/api";
import { percent } from "../lib/backtests";
import { dateAgo, number } from "../lib/research";
import type { Comparison, ComparisonTrack } from "../lib/strategyJourney";
import ChartCaption from "./ChartCaption";
import KLine from "./KLine";
import ResearchChart from "./ResearchChart";

const ACCOUNT_SYNC_START = "2025-01-20";

type ActualReview = {
  actual: { status: string; net_pnl?: string; fees?: string; xirr?: number | null; reasons?: string[] };
  markers: { trade_date: string; side: string; quantity: string; price: string }[];
  comparability: string;
};

function completedRoundMetrics(track: ComparisonTrack) {
  const diagnostics = track.diagnostics;
  const completed = diagnostics?.completed_rounds;
  const rounds = diagnostics?.rounds ?? [];
  const pnlValues = rounds.map((row) => Number(row.pnl));
  const complete = completed != null && Number.isInteger(completed) && completed >= 0
    && completed === rounds.length && pnlValues.every(Number.isFinite);
  const winRate = complete && completed === 0 ? "—（0 轮已完成）"
    : complete ? percent(pnlValues.filter((value) => value > 0).length / completed!) : "待核验";
  return {
    completed: completed == null ? "—" : String(completed),
    winRate,
    open: diagnostics?.open_rounds == null ? "—" : String(diagnostics.open_rounds),
  };
}

export default function StrategyComparison({ result, theme, renderAdoption }: {
  result: Comparison; theme: string; renderAdoption?: (track: ComparisonTrack) => ReactNode;
}) {
  const tradePanel = useRef<HTMLElement>(null);
  const [field, setField] = useState<"nav" | "drawdown">("nav");
  const [selected, setSelected] = useState("");
  const [actual, setActual] = useState<ActualReview>();
  const [overlayMarkers, setOverlayMarkers] = useState<ActualReview["markers"]>();
  const [opening, setOpening] = useState(false), [dates, setDates] = useState(false);
  const [showActual, setShowActual] = useState(false);
  const [actualError, setActualError] = useState("");
  const [tradeIndex, setTradeIndex] = useState(0);
  const [verification, setVerification] = useState("");
  const [verifyFailed, setVerifyFailed] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const tracks = result.tracks.filter((row) => row.account);
  const track = tracks.find((row) => row.key === selected) ?? tracks[0];
  const trade = track?.account?.trades[tradeIndex];
  const code = result.instrument_code, { start_date: start, end_date: end } = result.settings;
  const candles = useMemo<Omit<Candle, "amount">[]>(() => (result.market_rows ?? []).filter((row) => row.trade_date >= start && row.trade_date <= end).map((row) => ({ date: row.trade_date, open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close), volume: Number(row.volume), change_pct: null, source_updated_at: row.source_updated_at, collected_at: row.collected_at })), [result.market_rows, start, end]);
  const effectiveMarkers = actual?.markers ?? overlayMarkers ?? [];
  const klineTrades = useMemo(() => [
    ...(track?.account?.trades ?? []).map((row) => ({ ...row, quantity: String(row.quantity), source: "simulation" as const })),
    ...(showActual ? effectiveMarkers.map((row) => ({ ...row, source: "actual" as const })) : []),
  ], [track, showActual, effectiveMarkers]);
  const metricRows: [string, (row: ComparisonTrack) => string][] = [
    ["收益率", (row) => row.account ? percent(row.account.metrics.total_return) : row.reason ?? "本次未能完成计算"],
    ["最大回撤", (row) => row.account ? percent(row.account.metrics.max_drawdown) : "—"],
    ["模拟盈亏（元）", (row) => row.account ? number(Number(row.account.metrics.final_equity) - Number(result.settings.initial_cash)) : "—"],
    ["交易次数", (row) => row.account ? String(row.account.metrics.trade_count) : "—"],
    ["佣金／滑点成本（元）", (row) => row.account ? `${number(row.account.metrics.commission)}／${number(row.account.metrics.slippage_cost)}` : "—"],
    ["在场时间", (row) => row.account ? percent(row.diagnostics?.time_in_market ?? null) : "—"],
    ["已完成轮次", (row) => row.account ? completedRoundMetrics(row).completed : "—"],
    ["轮次胜率", (row) => row.account ? completedRoundMetrics(row).winRate : "—"],
    ["未平仓轮次", (row) => row.account ? completedRoundMetrics(row).open : "—"],
  ];
  useEffect(() => {
    const controller = new AbortController();
    setActual(undefined); setOverlayMarkers(undefined); setActualError("");
    const query = new URLSearchParams({ start, end, confirm_zero_opening: String(opening), confirm_trade_dates: String(dates) });
    api<ActualReview>(`/account/review/${code}?${query}`, "GET", undefined, controller.signal)
      .then(setActual).catch((e) => {
        if (controller.signal.aborted) return;
        setActualError(e.message);
        const markerStart = start < ACCOUNT_SYNC_START ? ACCOUNT_SYNC_START : start;
        const yesterday = dateAgo(1);
        const markerEnd = end >= dateAgo(0) ? yesterday : end;
        if (markerStart <= markerEnd && (markerStart !== start || markerEnd !== end)) {
          api<ActualReview>(`/account/review/${code}?${new URLSearchParams({ start: markerStart, end: markerEnd })}`, "GET", undefined, controller.signal)
            .then((fallback) => { if (!controller.signal.aborted) setOverlayMarkers(fallback.markers); })
            .catch(() => {});
        }
      });
    return () => controller.abort();
  }, [code, start, end, opening, dates]);
  async function verify() {
    setVerifying(true); setVerification(""); setVerifyFailed(false);
    try {
      const value = await api<{ identical: boolean }>(`/strategies/comparisons/${result.id}/verify`, "POST");
      setVerifyFailed(!value.identical);
      setVerification(value.identical ? "快照复算一致，未使用后来修订的数据。" : "复算不一致，请核查计算依据。");
    } catch (e) { setVerifyFailed(true); setVerification((e as Error).message); }
    finally { setVerifying(false); }
  }
  return <div className="journey-comparison">
    <div className="journey-section-heading"><div><h2>同一只 ETF，比较不同算法</h2><p className="muted mono">{code} · {start} 至 {end} · 研究本金 {number(result.settings.initial_cash)} 元</p></div><button disabled={verifying} onClick={() => void verify()}>{verifying ? "复算中…" : "核验这次比较"}</button></div>
    {!result.complete && <p className="notice warning">本次比较不完整，失败对象保留如下；不能将失败当作零收益。</p>}
    {verification && <p className={verifyFailed ? "notice warning" : "notice"} role={verifyFailed ? "alert" : "status"}>{verification}</p>}
    <p className="notice">行情数据截止：{result.data_cutoff ?? "未提供"}。{result.note ?? "历史结果为回测模拟，不代表实际收益。"} 实验模板的历史拟合不证明未来达到 80% 胜率。</p>
    <div className="strategy-matrix" role="region" aria-label="算法指标对照滚动区域" tabIndex={0}><table aria-label="算法指标对照"><thead><tr><th>比较指标</th>{result.tracks.map((row) => <th key={row.key}>{row.name}<p className="muted">{row.strategy_id === "hold" ? "持有参照" : "历史回测模拟"}</p></th>)}</tr></thead><tbody>
      {metricRows.map(([label, value]) => <tr key={label}><th scope="row">{label}</th>{result.tracks.map((row) => <td key={row.key}>{value(row)}</td>)}</tr>)}
      <tr><th scope="row">模拟交易解释</th>{result.tracks.map((row) => <td key={row.key}>{row.account ? <button onClick={() => { setSelected(row.key); setTradeIndex(0); tradePanel.current?.focus({ preventScroll: true }); tradePanel.current?.scrollIntoView({ block: "start" }); }} aria-pressed={track?.key === row.key}>查看买卖点</button> : "计算失败"}</td>)}</tr>
      {renderAdoption && <tr><th scope="row">采用到 {code}</th>{result.tracks.map((row) => <td key={row.key}>{renderAdoption(row)}</td>)}</tr>}
    </tbody></table></div>
    {result.tracks.some((row) => row.strategy_id !== "hold" && row.diagnostics?.sample_warning) && <p className="muted">
      完整平仓不足 5 轮的策略：{result.tracks.filter((row) => row.strategy_id !== "hold" && row.diagnostics?.sample_warning).map((row) => row.name).join("、")}。胜率样本较少。
    </p>}
    <section className="panel">
      <div className="panel-header"><h2>资金曲线与回撤</h2><div className="journey-actions"><button aria-pressed={field === "nav"} onClick={() => setField("nav")}>研究净值</button><button aria-pressed={field === "drawdown"} onClick={() => setField("drawdown")}>回撤</button></div></div>
      <ResearchChart theme={theme} unit={field === "nav" ? "净值" : "%"} series={tracks.map((row) => ({ name: `${row.name} · 模拟`, points: row.account!.daily.map((day) => [day.trade_date, day[field] * (field === "nav" ? 1 : 100)]) }))} />
      <ChartCaption title="同 ETF 算法对比" meta={`${code} · ${start}—${end} · 同区间、本金、成本和输入快照；最大回撤为阶段高点之后的最大跌幅`} />
    </section>
    <section ref={tradePanel} tabIndex={-1} className="panel algorithm-trade-panel">
      <div className="panel-header"><h2>{track?.name ?? "策略"} · 模拟买卖点</h2><label className="switch"><input type="checkbox" checked={showActual} onChange={(e) => setShowActual(e.target.checked)} />叠加真实操作</label></div>
      {candles.length ? <KLine rows={candles} theme={theme} positions={track?.account?.daily ?? []} onTrade={setTradeIndex} trades={klineTrades} /> : <div className="empty">本次比较未取得有效行情快照，无法绘制日 K</div>}
      {track?.account && !track.account.daily.some((day) => day.position_weight != null && Number.isFinite(day.position_weight)) && <p className="muted" role="status">模拟仓位账本缺失，无法展示每日仓位。</p>}
      <ChartCaption title={`${code} · 日 K、买卖点与模拟仓位`} meta="财通证券原始日行情的本次保存快照 · 复权口径未确认 · 模拟为三角标记，真实为图钉标记；真实标记日期为累计委托所属日，待核验；副图为每日收盘模拟仓位＝持仓市值÷账户总资产（含保留现金与应收分红），缺失不补零；叠加真实操作不改变模拟仓位" />
      {track?.account?.trades.length ? <div className="journey-inset"><label>逐次交易解释 <select value={tradeIndex} onChange={(e) => setTradeIndex(Number(e.target.value))}>{track.account.trades.map((row, index) => <option key={index} value={index}>{row.trade_date} · {row.side === "buy" ? "买入" : "卖出"} · {row.quantity} 份</option>)}</select></label>{trade && <p>信号日 <span className="mono">{trade.signal_date ?? "区间首日参照"}</span> → 模拟执行 <span className="mono">{trade.trade_date}</span>；{trade.reason}；价格 {trade.price} 元，佣金 {trade.commission} 元。</p>}</div> : <p className="journey-inset muted">这条策略在所选区间没有模拟成交。</p>}
    </section>
    <details className="panel journey-inset">
      <summary>我的真实操作 · 独立核算</summary>
      <p className="muted">实际资金路径与固定本金回测不同，不用真实 XIRR 减去回测收益率，也不将个人历史收益自动归属某条策略。</p>
      <div className="journey-confirmations"><label><input type="checkbox" checked={opening} onChange={(e) => setOpening(e.target.checked)} />依据对账资料确认：2025-01-20 同步起点前该 ETF 持仓为零</label><label><input type="checkbox" checked={dates} onChange={(e) => setDates(e.target.checked)} />依据对账资料确认：累计成交属于委托日期</label></div>
      {actualError ? <p className="notice warning">真实操作暂不可核算：{actualError}。策略比较仍可使用。</p> : !actual ? <p role="status">正在核验真实记录…</p> : actual.actual.status === "ready" || actual.actual.net_pnl != null ? <dl className="journey-metrics"><div><dt>真实净盈亏</dt><dd>{number(actual.actual.net_pnl)} 元</dd></div><div><dt>实际费用</dt><dd>{number(actual.actual.fees)} 元</dd></div><div><dt>真实 XIRR（非区间收益率）</dt><dd>{percent(actual.actual.xirr ?? null)}</dd></div></dl> : <div className="notice warning">{actual.actual.reasons?.join("；") ?? "暂无可核算的真实收益"}。可继续比较其他策略。</div>}
      {actual && <p className="muted">{actual.comparability}</p>}
    </details>
  </div>;
}
