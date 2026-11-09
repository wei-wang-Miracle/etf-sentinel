import { useState } from "react";
import { api, stamp, type Job } from "../lib/api";
import { dateAgo, number } from "../lib/research";
import { useApiResource } from "../lib/useApiResource";
import { executionNames, type Observation, type PlanSignal } from "../lib/strategyLab";
import { journeyUrl, type SavedStrategy } from "../lib/strategyJourney";
import { dataManagementUrl } from "../lib/navigation";
import { ExecutionForm } from "./ExecutionForm";

type ExtendedSignal = PlanSignal & { plan: PlanSignal["plan"] & {
  quantity_status?: string; new_trigger?: boolean; target_weight?: number;
  conditions?: Record<string, { label?: string; indicator?: string; matched?: boolean | null; satisfied?: boolean | null; value?: string | number | null; reason?: string; description?: string }[]>;
} };
const actionNames: Record<string, string> = { buy: "买入", sell: "卖出", hold: "继续持有", wait: "等待", unknown: "方向待核验" };

export default function DailySignals({ code, compact = false }: { code?: string; compact?: boolean }) {
  const signals = useApiResource<ExtendedSignal[]>("/strategy-lab/signals");
  const observations = useApiResource<Observation[]>("/strategy-lab/observations");
  const versions = useApiResource<SavedStrategy[]>("/strategies");
  const job = useApiResource<Job>("/strategy-lab/job");
  const [view, setView] = useState("current");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [blocked, setBlocked] = useState<{ instrument_code?: string; reason: string }[]>([]);
  const today = dateAgo(0);
  const activeVersions = (versions.error || versions.loading ? [] : versions.data ?? []).filter((row) => row.active && (!code || row.instrument_code === code));
  const activeObservations = (observations.error || observations.loading ? [] : observations.data ?? []).filter((row) => row.active && (!code || row.instrument_code === code));
  const activeIds = new Set(versions.error || observations.error || versions.loading || observations.loading ? [] : [...activeObservations.map((row) => row.id), ...activeVersions.flatMap((row) => row.observation_id == null ? [] : [row.observation_id])]);
  const hasActive = activeVersions.length > 0 || activeObservations.length > 0;
  const activeKnown = !versions.loading && !observations.loading && !versions.error && !observations.error;
  const rows = (signals.data ?? []).filter((row) => !code || row.instrument_code === code).sort((a, b) => b.generated_at.localeCompare(a.generated_at));
  const latest = new Map<number, ExtendedSignal>();
  rows.forEach((row) => { if (!signals.error && !signals.loading && row.execution_date >= today && activeIds.has(row.observation_id) && !latest.has(row.observation_id)) latest.set(row.observation_id, row); });
  const current = [...latest.values()];
  const shown = view === "history" ? rows.filter((row) => !current.some((item) => item.id === row.id)) : current;
  const recentIssues = (job.data?.runs[0]?.logs ?? []).filter((row) => ["failed", "blocked"].includes(row.status) && (!code || !(row.instrument_code ?? row.code) || (row.instrument_code ?? row.code) === code));
  const summaryText = !activeKnown ? "策略状态待读取或核验" : !hasActive ? "尚未启用策略，选择一只 ETF 开始研究。"
    : job.error ? "任务状态未取得，适用计划仍可查看。" : job.data && !job.data.enabled ? "每日自动运行已暂停，可检查任务5。"
      : current.length ? `${current.length} 条适用日期未过的计划，查看依据后再判断。`
        : recentIssues.length ? "最近运行存在阻断，请先核查原因。" : "尚无适用计划，等待下一次运行；也可核查最近运行记录。";
  const refresh = async () => { signals.retry(); observations.retry(); versions.retry(); job.retry(); };
  async function generate() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api<{ created: PlanSignal[]; existing: PlanSignal[]; blocked: { instrument_code?: string; reason: string }[] }>("/strategy-lab/signals/generate", "POST");
      setBlocked(code ? result.blocked.filter((row) => !row.instrument_code || row.instrument_code === code) : result.blocked);
      setNotice(`本次新增 ${result.created.length} 条计划，已有 ${result.existing.length} 条，阻断 ${result.blocked.length} 项。计划不是订单或成交。`);
      await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  if (compact) return <section className="signal-digest" aria-label="每日信号摘要">
    <div><span className="digest-label">每日信号</span><p role="status">{signals.loading ? "正在读取信号…" : signals.error ? `信号读取失败：${signals.error}` : summaryText}</p></div>
    {hasActive || rows.length ? <a href={journeyUrl("etfs", code ?? current[0]?.instrument_code ?? rows[0]?.instrument_code ?? activeVersions[0]?.instrument_code ?? activeObservations[0]?.instrument_code, { detail: "signals" })}>查看信号与依据</a>
      : <a href={journeyUrl("strategies", code)}>查看策略</a>}
  </section>;

  return <section className="signals-workspace" aria-label="每日信号与执行记录">
    <div className="signal-heading"><div><h2>每日信号</h2><p className="muted">{job.loading ? "任务状态读取中" : job.error ? "任务状态未取得" : !job.data?.enabled ? "每日自动运行已暂停" : job.data.next_run ? `下次任务：${stamp(job.data.next_run)}` : "下次运行时间待核验"} · 北京时间 · 不自动下单</p></div><button disabled={busy || signals.loading || !activeKnown || !hasActive} onClick={() => void generate()}>{busy ? "核验数据并计算…" : "检查并生成盘前信号"}</button></div>
    {shown.length > 0 && <p className="context-note">{summaryText}</p>}
    <div className="signal-controls"><div className="segmented" role="group" aria-label="信号记录范围"><button aria-pressed={view === "current"} onClick={() => setView("current")}>适用计划</button><button aria-pressed={view === "history"} onClick={() => setView("history")}>历史记录</button></div><a href={dataManagementUrl("jobs", "strategy-signals", code)}>检查信号任务</a></div>
    {error && <p className="alert" role="alert">{error}</p>}
    {signals.error && <p className="alert" role="alert">信号读取失败：{signals.error}<button onClick={signals.retry}>重试信号</button></p>}
    {(versions.error || observations.error) && <p className="notice warning">部分策略状态未取得；无法核验的计划只在历史记录中展示。<button onClick={() => { versions.retry(); observations.retry(); }}>重试策略状态</button></p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {blocked.map((row, index) => <p key={index} className="notice warning">{row.instrument_code ?? "日计划"} · 暂不可生成：{row.reason} <a href={dataManagementUrl("jobs", "strategy-signals", row.instrument_code ?? code)}>检查日计划依赖记录</a></p>)}
    {recentIssues.map((row, index) => <p className="notice warning" key={index}>最近运行：{row.message}</p>)}
    {signals.loading ? <div className="empty skeleton-state" role="status">正在读取信号…</div> : !shown.length && !signals.error ? <div className="empty"><h3>{view === "history" ? "暂无历史记录" : "尚无适用计划"}</h3><p>{view === "history" ? "已经过期或来自旧版本的计划会保留在这里。" : summaryText}</p><a href={hasActive ? dataManagementUrl("jobs", "strategy-signals", code) : journeyUrl("strategies", code)}>{hasActive ? "查看最近运行记录" : "为这只 ETF 配置策略"}</a></div>
      : <div className="journey-signal-list">{shown.map((row) => {
        const quantityUnknown = row.plan.quantity_status === "unknown" || row.plan.actual_quantity == null;
        const observation = observations.data?.find((item) => item.id === row.observation_id);
        const version = versions.data?.find((item) => item.observation_id === row.observation_id);
        const isCurrent = current.some((item) => item.id === row.id);
        const action = row.plan.new_trigger === false ? row.plan.target_weight ? "继续持有" : "等待" : row.plan.action === "hold" && Number(row.plan.target_quantity) === 0 ? "等待" : actionNames[row.plan.action] ?? "方向待核验";
        return <article key={row.id} className="journey-signal">
          <div className="journey-section-heading"><h3><span className="mono">{row.instrument_code}</span> · {action}</h3><span className="badge neutral">{quantityUnknown ? "数量待核验" : executionNames[row.execution.status] ?? row.execution.status}</span></div>
          <p className="signal-version">{version ? `${version.name} · 第${version.version}版` : observation?.rule.name ?? "历史观察策略"}{!isCurrent && " · 历史记录"}</p>
          {!isCurrent && <p className="notice warning">这是历史计划，或所属版本已不再启用；仅用于复盘，不作为今天的操作指令。</p>}
          <dl className="journey-metrics"><div><dt>适用交易日</dt><dd>{row.execution_date}</dd></div><div><dt>数据截止</dt><dd>{row.data_cutoff}</dd></div><div><dt>生成时间</dt><dd>{stamp(row.generated_at)}</dd></div><div><dt>事件状态</dt><dd>{row.plan.new_trigger == null ? "待核验" : row.plan.new_trigger ? "本次新触发" : "延续上一轮目标"}</dd></div></dl>
          <p className="signal-reason">{row.plan.reason}</p>
          {row.plan.new_trigger === false && <p className="muted">沿用本轮参考份额；不是今天新触发的买卖事件，持续持有不每日按价调仓。</p>}
          <dl className="journey-metrics"><div><dt>参考目标</dt><dd>{quantityUnknown || row.plan.target_quantity == null ? "方向已计算，数量待核验" : `${number(row.plan.target_quantity, 0)} 份`}</dd></div><div><dt>真实／可用份额</dt><dd>{quantityUnknown ? "尚无完整仓位证据" : `${number(row.plan.actual_quantity, 0)}／${number(row.plan.available_quantity, 0)}`}</dd></div></dl>
          {row.plan.funding_check_required && <p className="notice warning">买入前须人工核验可用现金，研究本金不代表实际可用资金。</p>}
          {(row.plan.warnings ?? []).map((warning, index) => <p className="notice warning" key={index}>{warning}</p>)}
          {row.plan.conditions && <details><summary>逐条条件与当时数值</summary>{Object.entries(row.plan.conditions).map(([group, conditions]) => <section key={group}><h4>{group === "buy" ? "买入" : "卖出"}条件</h4>{conditions.map((item, index) => { const matched = item.satisfied ?? item.matched; return <p key={index}>{item.label ?? item.description ?? item.indicator ?? `条件 ${index + 1}`}：{matched == null ? "未知" : matched ? "满足" : "不满足"}；当时数值 {item.value ?? "缺失"}{item.reason ? ` · ${item.reason}` : ""}</p>; })}</section>)}</details>}
          <details><summary>仓位与版本依据</summary><p>{row.plan.position_basis ?? "仓位依据待核验"} · 观察记录 #{row.observation_id}</p><p>计划不等于订单或成交，累计委托只作为匹配候选；卖出以可用份额为约束。</p></details>
          {!quantityUnknown && <ExecutionForm signal={row} refresh={refresh} report={setError} />}
          {row.skip_note && <p>主动跳过：{row.skip_note}</p>}
          {row.execution.links.map((link) => <p key={link.id} className={link.source_revised ? "notice warning" : "muted"}>已关联委托 {link.entrust_no} · {link.confirmed_trade_date} · {link.source_revised ? "源数量已修订，请重新核对" : link.confirmation_note}</p>)}
        </article>;
      })}</div>}
  </section>;
}
