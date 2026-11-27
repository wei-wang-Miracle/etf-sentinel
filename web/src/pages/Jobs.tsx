import { useEffect, useRef, useState } from "react";
import { api, stamp, statusNames, type Job, type Run } from "../lib/api";
import { useResearchQuery } from "../lib/research";
import Tabs from "../components/Tabs";

export default function Jobs({
  initialTask = "etf",
}: {
  initialTask?: string;
}) {
  const [query, update] = useResearchQuery({ task: initialTask });
  const tasks = [["etf", "基金日行情"], ["etf-flows", "ETF档案与份额流"], ["sentiment", "行业恐贪"], ["market-sentiment", "全市场温度"], ["national-team", "国家队持仓"], ["index-valuations", "指数估值"], ["strategy-signals", "策略日计划"]];
  const task = tasks.some(([key]) => key === query.task) ? query.task : "etf";
  return (
    <>
      <Tabs label="任务分类" items={tasks.map(([value, label]) => ({ value, label }))} value={task} onChange={(task) => update({ task })}>
        <TaskPanel key={task} task={task} />
      </Tabs>
    </>
  );
}
function TaskPanel({ task }: { task: string }) {
  const path = task === "strategy-signals" ? "/strategy-lab/job" : task === "index-valuations" ? "/index-valuations/job" : task === "national-team" ? "/national-team/job" : task === "market-sentiment" ? "/market-sentiment/job" : task === "etf-flows" ? "/etf-flows/job" : task === "sentiment" ? "/sentiment/job" : "/job";
  const [job, setJob] = useState<Job | null>(null);
  const [time, setTime] = useState("01:00");
  const [enabled, setEnabled] = useState(true);
  const [pollError, setPollError] = useState("");
  const [actionError, setActionError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const logPanelRef = useRef<HTMLElement>(null);
  async function load(initial = false, signal?: AbortSignal) {
    try {
      const data = await api<Job>(path, "GET", undefined, signal);
      if (signal?.aborted) return;
      setJob(data);
      setPollError("");
      if (initial) {
        setTime(data.time);
        setEnabled(data.enabled);
      }
    } catch (e) {
      if (!signal?.aborted) setPollError((e as Error).message);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(true, controller.signal);
    const timer = setInterval(() => void load(false, controller.signal), 3000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (selected != null) {
      logPanelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      logPanelRef.current?.focus({ preventScroll: true });
    }
  }, [selected]);
  const running = job?.runs.some((r) => r.status === "running");
  const detail: Run | undefined = job?.runs.find((r) => r.id === selected);
  async function action(kind: "save" | "run") {
    setBusy(true);
    setMessage("");
    setActionError("");
    try {
      await api(
        kind === "save" ? path : `${path}/run`,
        kind === "save" ? "PUT" : "POST",
        kind === "save" ? { enabled, time } : undefined,
      );
      setMessage(
        kind === "save" ? "任务配置已保存" : "已启动，运行记录会自动更新",
      );
      await load();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const error = actionError || pollError;
  return (
    <>
      <header className="page-header">
        <div>
          <h2>定时任务</h2>
          <p>{task === "etf" ? "基金行情回补与权益资料批量核验" : task === "etf-flows" ? "配置内 ETF 档案核验与日度份额流沉淀" : "历史回补与每日增量，采集进度按区间保存"}</p>
        </div>
        <button
          className="primary"
          disabled={busy || running || !job?.source_configured}
          onClick={() => action("run")}
        >
          {running ? "运行中…" : task === "strategy-signals" ? "生成日计划" : "立即采集"}
        </button>
      </header>
      {error && (
        <div className="alert" role="alert">
          <span>{error}</span>
          <button onClick={() => { setActionError(""); void load(!job); }}>重试</button>
        </div>
      )}
      {job && !job.source_configured && (
        <div className="notice warning">
          数据源尚未配置。请在后端环境变量中设置行情访问令牌与访问码，然后重启后端服务。
        </div>
      )}
      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}
      <section className="panel">
        <div className="panel-header">
          <h2>{task === "strategy-signals" ? "观察策略日计划" : task === "index-valuations"
            ? "指数估值与指数日K采集"
            : task === "national-team" ? "国家队持仓比例采集" : task === "market-sentiment" ? "全市场温度采集" : task === "sentiment" ? "行业恐贪采集" : "基金日行情与权益资料核验"}</h2>
          <span
            className={`badge ${running ? "info" : job?.enabled ? "success" : "neutral"}`}
          >
            {running ? "运行中" : job?.enabled ? "定时已启用" : "定时已暂停"}
          </span>
        </div>
        {!job ? (
          <div className="empty">正在读取任务配置…</div>
        ) : (
          <div className="job-settings">
            <label>
              每日执行时间{" "}
              <input
                aria-label="每日执行时间"
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
              <span className="subtext">北京时间（东八区）</span>
            </label>
            <label className="switch">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              启用每日调度
            </label>
            <div>
              <span className="muted">下次执行</span>
              <div className="mono">{stamp(job.next_run)}</div>
            </div>
            <button
              disabled={
                busy || !time || (time === job.time && enabled === job.enabled)
              }
              onClick={() => action("save")}
            >
              保存配置
            </button>
          </div>
        )}
        <details className="job-rule-details">
          <summary>采集与调度口径</summary>
          <p>
            {task === "strategy-signals"
              ? "默认 08:30，仅为已采用策略生成尚未开盘交易日的计划；行情或持仓过期、权益未核验会阻止生成，开盘后不补写。"
              : task === "index-valuations"
              ? "8 个关联指数，5 类日频估值全历史核验、增量写入；指数日 K 首次按月回填，后续七日交叠，失败区间重试。"
              : task === "national-team"
              ? "采集源页面 18 只基金估算持仓比例，固定 2026-01-01 基准，全历史核验并增量写入。"
              : task === "sentiment"
              ? "首次回填五年，后续增量入库并重查最近七日修订。"
              : task === "market-sentiment"
              ? "全市场恐贪总分自2020-08起增量核验；五维子因子只返回近一年滚动窗口，按日累积且不删除本地旧历史。"
              : task === "etf-flows"
              ? "拉取配置内ETF的费率、成立日、跟踪指数关联参考及T-1份额净变动和折溢价；仅从首次采集日起逐日沉淀，不回填未采集历史。"
              : "行情采集截至昨日：启用标的首次按月回补，后续重查最近七日；随后核验全部配置 ETF 分红与折算资料。"}{" "}
            同一任务禁止重复触发。
          </p>
        </details>
      </section>
      <section className="panel">
        <div className="panel-header">
          <h2>运行记录</h2>
          <span className="muted">最近 20 次 · 自动刷新</span>
        </div>
        {!job ? (
          <div className="empty" role="status">正在读取运行记录…</div>
        ) : job.runs.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>运行编号</th>
                  <th>触发方式</th>
                  <th>开始时间</th>
                  <th>结束时间</th>
                  <th>处理记录</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {job.runs.map((run) => (
                  <tr key={run.id}>
                    <td className="mono">#{run.id}</td>
                    <td>{run.trigger === "manual" ? "手动" : "定时"}</td>
                    <td className="mono">{stamp(run.started_at)}</td>
                    <td className="mono">{stamp(run.ended_at)}</td>
                    <td>
                      {run.logs.length} 条 /{" "}
                      {run.logs.filter((l) => l.status === "failed").length} 条失败
                    </td>
                    <td>
                      <span className={`badge ${run.status}`}>
                        {statusNames[run.status]}
                      </span>
                    </td>
                    <td>
                      <button
                        aria-pressed={selected === run.id}
                        onClick={() =>
                          setSelected(selected === run.id ? null : run.id)
                        }
                      >
                        {selected === run.id ? "收起日志" : "查看日志"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            还没有运行记录。配置完成后，点击“立即采集”更新行情并核验权益资料。
          </div>
        )}
      </section>
      {detail && (
        <section ref={logPanelRef} tabIndex={-1} className="panel" aria-label={`运行 ${detail.id} 处理明细`}>
          <div className="panel-header">
            <h2>运行 #{detail.id} · 处理明细</h2>
            <button onClick={() => setSelected(null)}>关闭日志</button>
          </div>
          <div className="logs" aria-live="polite">
            {!detail.logs.length && <p>等待首个区间完成…</p>}
            {detail.logs.map((log, i) => (
              <div className="log-line" key={i}>
                <span
                  className={
                    log.status === "failed" ? "danger-text" : "success-text"
                  }
                >
                  {log.status === "failed" ? "失败" : "成功"}
                </span>
                <span>
                  {log.kind === "equity" ? "权益资料" : "日行情"} · {log.code ?? "系统"}
                  {log.kind !== "equity" && log.start && ` ${log.start} ～ ${log.end}`}
                </span>
                <span>{log.kind === "equity" ? "" : `${log.count ?? 0} 条`}</span>
                <span>{log.message}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
