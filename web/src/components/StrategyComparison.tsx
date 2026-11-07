import { useEffect, useState } from "react";
import { api, type Candle } from "../lib/api";
import { percent } from "../lib/backtests";
import { number } from "../lib/research";
import type { Comparison } from "../lib/strategyJourney";
import ChartCaption from "./ChartCaption";
import KLine from "./KLine";
import ResearchChart from "./ResearchChart";

type ActualReview = {
  actual: { status: string; net_pnl?: string; fees?: string; xirr?: number | null; reasons?: string[] };
  markers: { trade_date: string; side: string; quantity: string; price: string }[];
  comparability: string;
};

export default function StrategyComparison({ result, theme }: { result: Comparison; theme: string }) {
  const [field, setField] = useState<"nav" | "drawdown">("nav");
  const [selected, setSelected] = useState("");
  const [actual, setActual] = useState<ActualReview>();
  const [opening, setOpening] = useState(false), [dates, setDates] = useState(false);
  const [showActual, setShowActual] = useState(false);
  const [actualError, setActualError] = useState("");
  const [tradeIndex, setTradeIndex] = useState(0);
  const [verification, setVerification] = useState("");
  const [verifying, setVerifying] = useState(false);
  const tracks = result.tracks.filter((row) => row.account);
  const track = tracks.find((row) => row.key === selected) ?? tracks[0];
  const trade = track?.account?.trades[tradeIndex];
  const code = result.instrument_code, { start_date: start, end_date: end } = result.settings;
  const candles: Omit<Candle, "amount">[] = (result.market_rows ?? []).filter((row) => row.trade_date >= start && row.trade_date <= end).map((row) => ({ date: row.trade_date, open: Number(row.open), high: Number(row.high), low: Number(row.low), close: Number(row.close), volume: Number(row.volume), change_pct: null, source_updated_at: row.source_updated_at, collected_at: row.collected_at }));
  useEffect(() => { setOpening(false); setDates(false); setSelected(""); setTradeIndex(0); setVerification(""); }, [result.id]);
  useEffect(() => {
    const controller = new AbortController();
    setActual(undefined); setActualError("");
    const query = new URLSearchParams({ start, end, confirm_zero_opening: String(opening), confirm_trade_dates: String(dates) });
    api<ActualReview>(`/account/review/${code}?${query}`, "GET", undefined, controller.signal)
      .then(setActual).catch((e) => { if (!controller.signal.aborted) setActualError(e.message); });
    return () => controller.abort();
  }, [code, start, end, opening, dates]);
  async function verify() {
    setVerifying(true); setVerification("");
    try {
      const value = await api<{ identical: boolean }>(`/strategies/comparisons/${result.id}/verify`, "POST");
      setVerification(value.identical ? "快照复算一致，未使用后来修订的数据。" : "复算不一致，请核查计算依据。");
    } catch (e) { setVerification((e as Error).message); }
    finally { setVerifying(false); }
  }
  return <div className="journey-comparison">
    <div className="journey-section-heading"><div><h2>同一只 ETF，比较不同方法</h2><p className="muted mono">{code} · {start} 至 {end} · 研究本金 {number(result.settings.initial_cash)} 元</p></div><button disabled={verifying} onClick={() => void verify()}>{verifying ? "复算中…" : "核验这次比较"}</button></div>
    {!result.complete && <p className="notice warning">本次比较不完整，失败对象保留如下；不能将失败当作零收益。</p>}
    {verification && <p className="notice" role="status">{verification}</p>}
    <div className="strategy-matrix" role="region" aria-label="策略指标对照滚动区域" tabIndex={0}><table aria-label="策略指标对照"><thead><tr><th>比较指标</th>{result.tracks.map((row) => <th key={row.key}>{row.name}<p className="muted">{row.evidence_type.includes("revis") ? "修订历史研究 · 未证明当时可得" : "历史回测模拟"}</p></th>)}</tr></thead><tbody>
      {["收益率", "最大回撤", "模拟盈亏（元）", "交易次数", "佣金／滑点成本（元）", "在场时间"].map((label, index) => <tr key={label}><th scope="row">{label}</th>{result.tracks.map((row) => <td key={row.key}>{row.account ? [percent(row.account.metrics.total_return), percent(row.account.metrics.max_drawdown), number(Number(row.account.metrics.final_equity) - Number(result.settings.initial_cash)), row.account.metrics.trade_count, `${number(row.account.metrics.commission)}／${number(row.account.metrics.slippage_cost)}`, percent(row.diagnostics?.time_in_market ?? null)][index] : index === 0 ? row.reason ?? "本次未能完成计算" : "—"}</td>)}</tr>)}
      <tr><th scope="row">模拟交易解释</th>{result.tracks.map((row) => <td key={row.key}>{row.account ? <button onClick={() => { setSelected(row.key); setTradeIndex(0); }} aria-pressed={track?.key === row.key}>查看买卖点</button> : "计算失败"}</td>)}</tr>
    </tbody></table></div>
    <section className="panel">
      <div className="panel-header"><h2>资金曲线与回撤</h2><div className="journey-actions"><button aria-pressed={field === "nav"} onClick={() => setField("nav")}>研究净值</button><button aria-pressed={field === "drawdown"} onClick={() => setField("drawdown")}>回撤</button></div></div>
      <ResearchChart theme={theme} unit={field === "nav" ? "净值" : "%"} series={tracks.map((row) => ({ name: `${row.name} · 模拟`, points: row.account!.daily.map((day) => [day.trade_date, day[field] * (field === "nav" ? 1 : 100)]) }))} />
      <ChartCaption title="同 ETF 策略对比" meta={`${code} · ${start}—${end} · 同区间、本金、成本和输入快照；最大回撤为阶段高点之后的最大跌幅`} />
    </section>
    <section className="panel">
      <div className="panel-header"><h2>{track?.name ?? "策略"} · 模拟买卖点</h2><label className="switch"><input type="checkbox" checked={showActual} onChange={(e) => setShowActual(e.target.checked)} />叠加真实操作</label></div>
      {candles.length ? <KLine rows={candles} theme={theme} onTrade={setTradeIndex} trades={[...(track?.account?.trades ?? []).map((row) => ({ ...row, quantity: String(row.quantity), source: "simulation" as const })), ...(showActual ? (actual?.markers ?? []).map((row) => ({ ...row, source: "actual" as const })) : [])]} /> : <div className="empty">本次比较未取得有效行情快照，无法绘制日 K</div>}
      <ChartCaption title={`${code} · 日 K 与买卖点`} meta="财通证券原始日行情的本次冻结快照 · 复权口径未确认 · 模拟为三角标记，真实为图钉标记；真实标记日期为累计委托所属日，待核验" />
      {track?.account?.trades.length ? <div className="journey-inset"><label>逐次交易解释 <select value={tradeIndex} onChange={(e) => setTradeIndex(Number(e.target.value))}>{track.account.trades.map((row, index) => <option key={index} value={index}>{row.trade_date} · {row.side === "buy" ? "买入" : "卖出"} · {row.quantity} 份</option>)}</select></label>{trade && <p>信号日 <span className="mono">{trade.signal_date ?? "区间首日参照"}</span> → 模拟执行 <span className="mono">{trade.trade_date}</span>；{trade.reason}；价格 {trade.price} 元，佣金 {trade.commission} 元。</p>}</div> : <p className="journey-inset muted">这条策略在所选区间没有模拟成交。</p>}
    </section>
    <details className="panel journey-inset">
      <summary>我的真实操作 · 独立核算</summary>
      <p className="muted">实际资金路径与固定本金回测不同，不用真实 XIRR 减去回测收益率，也不将个人历史收益自动归属某条策略。</p>
      <div className="journey-confirmations"><label><input type="checkbox" checked={opening} onChange={(e) => setOpening(e.target.checked)} />依据对账资料确认：2025-01-20 同步起点前该 ETF 持仓为零</label><label><input type="checkbox" checked={dates} onChange={(e) => setDates(e.target.checked)} />依据对账资料确认：累计成交属于委托日期</label></div>
      {actualError ? <p className="notice warning">真实操作暂不可核算：{actualError}。策略比较仍可使用。</p> : !actual ? <p role="status">正在核验真实记录…</p> : actual.actual.status === "ready" || actual.actual.net_pnl != null ? <dl className="journey-metrics"><div><dt>真实净盈亏</dt><dd>{number(actual.actual.net_pnl)} 元</dd></div><div><dt>实际费用</dt><dd>{number(actual.actual.fees)} 元</dd></div><div><dt>真实 XIRR（非区间收益率）</dt><dd>{percent(actual.actual.xirr ?? null)}</dd></div></dl> : <div className="notice warning">{actual.actual.reasons?.join("；") ?? "暂无可核算的真实收益"}。可继续比较其他策略。</div>}
      {actual && <p className="muted">{actual.comparability}</p>}
    </details>
    <details className="journey-inset"><summary>本次计算依据</summary><p>佣金率 {result.settings.commission_rate}，最低佣金 {result.settings.minimum_commission} 元，不利滑点 {result.settings.slippage_bps} 基点。输入摘要 <span className="journey-digest mono">{result.input_sha256}</span>。</p><p>每条策略保留自身规则和投入比例。研究模拟不等于真实收益；没有自动选择或启用胜者。</p></details>
  </div>;
}
