import { useCallback, useEffect, useState } from "react";
import { api, stamp } from "../lib/api";
import { dateAgo, number } from "../lib/research";
import { executionNames, type Observation, type PlanSignal } from "../lib/strategyLab";
import { journeyUrl } from "../lib/strategyJourney";
import { ExecutionForm } from "./StrategyLab";

type ExtendedSignal = PlanSignal & { plan: PlanSignal["plan"] & {
  quantity_status?: string;
  new_trigger?: boolean;
  target_weight?: number;
  conditions?: Record<string, { label?: string; indicator?: string; matched?: boolean | null; satisfied?: boolean | null; value?: string | number | null; reason?: string; description?: string }[]>;
} };
const actionNames: Record<string, string> = { buy: "买入", sell: "卖出", hold: "继续持有", wait: "等待", unknown: "方向待核验" };

export default function DailySignals({ code, compact = false }: { code?: string; compact?: boolean }) {
  const [signals, setSignals] = useState<ExtendedSignal[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [blocked, setBlocked] = useState<{ instrument_code?: string; reason: string }[]>([]);
  const [job, setJob] = useState<{ next_run: string | null; enabled: boolean; runs: { logs: { status: string; message: string; instrument_code?: string }[] }[] }>();
  const refresh = useCallback(async () => {
    const [rows, versions, currentJob] = await Promise.all([api<ExtendedSignal[]>("/strategy-lab/signals"), api<Observation[]>("/strategy-lab/observations"), api<NonNullable<typeof job>>("/strategy-lab/job")]);
    setSignals(code ? rows.filter((row) => row.instrument_code === code) : rows);
    setObservations(versions);
    setJob(currentJob);
  }, [code]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setSignals([]);
    Promise.all([api<ExtendedSignal[]>("/strategy-lab/signals"), api<NonNullable<typeof job>>("/strategy-lab/job"), api<Observation[]>("/strategy-lab/observations")])
      .then(([rows, current, versions]) => { if (!cancelled) { setSignals(code ? rows.filter((row) => row.instrument_code === code) : rows); setJob(current); setObservations(versions); } })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code]);
  async function generate() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<{ created: PlanSignal[]; existing: PlanSignal[]; blocked: { instrument_code?: string; reason: string }[] }>("/strategy-lab/signals/generate", "POST");
      setBlocked(code ? result.blocked.filter((row) => !row.instrument_code || row.instrument_code === code) : result.blocked);
      setNotice(`本次新增 ${result.created.length} 条计划，已有 ${result.existing.length} 条，阻断 ${result.blocked.length} 项。计划不是订单或成交。`);
      await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const today = dateAgo(0);
  const currentSignals = new Map<number, ExtendedSignal>();
  [...signals].sort((a, b) => b.generated_at.localeCompare(a.generated_at)).forEach((row) => {
    if (row.execution_date >= today && observations.some((version) => version.id === row.observation_id && version.active) && !currentSignals.has(row.observation_id)) currentSignals.set(row.observation_id, row);
  });
  const latest = [...currentSignals.values()];
  const shown = compact ? latest : signals;
  return <section className={`panel journey-inset journey-daily-signals ${compact ? "compact" : ""}`}>
    <div className="journey-section-heading"><div><h2>{compact ? "今日与下一交易日信号" : "每日信号与执行记录"}</h2><p className="muted">{!job ? "任务状态待读取" : job.enabled ? `下次自动运行：${stamp(job.next_run)}` : "每日自动运行已暂停，可到数据管理启用"} · 不自动下单</p></div><button disabled={busy || loading} onClick={() => void generate()}>{busy ? "核验数据并计算…" : "检查并生成盘前信号"}</button></div>
    {error && <p className="alert" role="alert">{error}<button onClick={() => void refresh().then(() => setError("")).catch((e) => setError(e.message))}>重试</button></p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {blocked.map((row, index) => <p key={index} className="notice warning">{row.instrument_code ?? "日计划"} · 数据待更新／暂不可生成：{row.reason} <a href={journeyUrl("data")}>检查数据</a></p>)}
    {job?.runs[0]?.logs.filter((row) => row.status === "failed" || row.status === "blocked").map((row, index) => <p className="notice warning" key={`log-${index}`}>最近自动运行：{row.message}</p>)}
    {loading ? <p className="empty" role="status">正在读取信号…</p> : !shown.length ? <div className="empty"><p>{signals.length ? "暂无适用于今天或下一交易日的新信号，旧信号不作为今日指令。" : "尚无信号。保存并启用一条策略后，系统才开始每日运行。"}</p><a href={journeyUrl("strategies", code)}>配置或查看策略</a></div> : <div className="journey-signal-list">{shown.map((row) => {
      const quantityUnknown = row.plan.quantity_status === "unknown" || row.plan.actual_quantity == null;
      const observation = observations.find((version) => version.id === row.observation_id);
      const action = row.plan.new_trigger === false ? row.plan.target_weight ? "继续持有" : "等待" : row.plan.action === "hold" && Number(row.plan.target_quantity) === 0 ? "等待" : actionNames[row.plan.action] ?? "等待";
      return <article key={row.id} className="journey-signal"><div className="journey-section-heading"><h3><a href={journeyUrl("etfs", row.instrument_code)}>{row.instrument_code}</a> · {action}</h3><span className="badge neutral">{quantityUnknown ? "数量待核验" : executionNames[row.execution.status] ?? row.execution.status}</span></div>
        <p className="muted">{observation?.rule.name ?? "观察策略"} · 观察版本 #{row.observation_id}{observation?.active ? " · 当前运行" : " · 已暂停或被替换，仅作历史复盘"}</p>
        {row.plan.new_trigger === false && <p className="muted">持续目标差异或持有状态，沿用本轮参考份额；不是今天新触发的买卖事件。</p>}
        <p>{row.plan.reason}</p>
        {row.plan.conditions && Object.entries(row.plan.conditions).map(([group, conditions]) => <details key={group}><summary>{group === "buy" ? "买入" : "卖出"}条件逐条依据</summary>{conditions.map((item, index) => { const matched = item.satisfied ?? item.matched; return <p key={index}>{item.label ?? item.description ?? item.indicator ?? `条件 ${index + 1}`}：{matched == null ? "未知" : matched ? "满足" : "不满足"}；当时数值 {item.value ?? "缺失"}{item.reason ? ` · ${item.reason}` : ""}</p>; })}</details>)}
        <dl className="journey-metrics"><div><dt>参考目标</dt><dd>{quantityUnknown ? "方向已计算，数量待核验" : `${number(row.plan.target_quantity, 0)} 份`}</dd></div><div><dt>真实／可用份额</dt><dd>{quantityUnknown ? "尚无完整仓位证据" : `${number(row.plan.actual_quantity, 0)}／${number(row.plan.available_quantity, 0)}`}</dd></div><div><dt>数据截止</dt><dd>{row.data_cutoff}</dd></div><div><dt>适用交易日</dt><dd>{row.execution_date}</dd></div></dl>
        <p className="muted">生成于 {stamp(row.generated_at)} · {row.plan.position_basis} {row.plan.funding_check_required ? "买入前须人工核验可用现金。" : ""}</p>
        {row.execution_date < today && <p className="notice warning">这是历史计划，仅用于复盘，不作为今天的操作指令。</p>}
        {row.plan.warnings.map((warning, index) => <p className="notice warning" key={index}>{warning}</p>)}
        {!compact && !quantityUnknown && <ExecutionForm signal={row} refresh={refresh} report={setError} />}
        {row.skip_note && <p>主动跳过：{row.skip_note}</p>}
        {row.execution.links.map((link) => <p key={link.id} className={link.source_revised ? "notice warning" : "muted"}>已关联委托 {link.entrust_no} · {link.confirmed_trade_date} · {link.source_revised ? "源数量已修订，请重新核对" : link.confirmation_note}</p>)}
      </article>;
    })}</div>}
  </section>;
}
