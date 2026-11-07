import { useEffect, useState } from "react";
import { api, stamp } from "../lib/api";
import { percent, type Account } from "../lib/backtests";
import {
  executionNames,
  type Batch,
  type EntrustCandidate,
  type LabCatalog,
  type Observation,
  type ObservationReview,
  type Period,
  type PlanSignal,
  type Track,
  type Windows,
} from "../lib/strategyLab";
import ResearchChart from "./ResearchChart";

const root = "/strategy-lab";
const number = (value: string | number) =>
  Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const blankWindows: Windows = {
  development_start: "",
  development_end: "",
  validation_start: "",
  validation_end: "",
};
function AccountChart({
  accounts,
  theme,
}: {
  accounts: { name: string; account: Account }[];
  theme: string;
}) {
  const [field, setField] = useState<"nav" | "drawdown" | "position_weight">(
    "nav",
  );
  return (
    <>
      <div className="chart-toolbar">
        <label>
          图表指标{" "}
          <select
            value={field}
            onChange={(e) => setField(e.target.value as typeof field)}
          >
            <option value="nav">研究净值</option>
            <option value="drawdown">回撤</option>
            <option value="position_weight">仓位</option>
          </select>
        </label>
      </div>
      <ResearchChart
        theme={theme}
        unit={field === "nav" ? "净值" : "%"}
        series={accounts.map(({ name, account }) => ({
          name,
          points: account.daily.map((row) => [
            row.trade_date,
            row[field] * (field === "nav" ? 1 : 100),
          ]),
        }))}
      />
    </>
  );
}
export function ExecutionForm({
  signal,
  refresh,
  report,
}: {
  signal: PlanSignal;
  refresh: () => Promise<void>;
  report: (message: string) => void;
}) {
  const [candidates, setCandidates] = useState<EntrustCandidate[] | null>(null);
  const [chosen, setChosen] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [planPreceded, setPlanPreceded] = useState(false);
  const [busy, setBusy] = useState(false);
  async function action(operation: () => Promise<unknown>) {
    setBusy(true);
    try {
      await operation();
      await refresh();
    } catch (e) {
      report((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const candidate = candidates?.find((row) => row.entrust_no === chosen);
  return (
    <details className="backtest-assumptions">
      <summary>核对真实累计委托／主动跳过</summary>
      <p>
        委托匹配仅为候选，不代表已执行；请先同步真实成交，再依据券商明细确认成交日期和计划在先。
      </p>
      <button
        disabled={busy}
        onClick={() =>
          void action(async () => {
            const rows = await api<EntrustCandidate[]>(
              `${root}/signals/${signal.id}/candidates`,
            );
            setCandidates(rows);
            setChosen("");
          })
        }
      >
        读取累计委托候选
      </button>
      {candidates && (
        <>
          <label>
            累计委托{" "}
            <select value={chosen} onChange={(e) => setChosen(e.target.value)}>
              <option value="">请明确选择</option>
              {candidates.map((row) => (
                <option key={row.entrust_no} value={row.entrust_no}>
                  {row.entrust_no} · {row.curr_date} · {number(row.quantity)}份
                  · {row.price}元
                </option>
              ))}
            </select>
          </label>
          {!candidates.length && (
            <p>暂无符合标的、方向及日期的累计成交候选。</p>
          )}
          {candidate && (
            <p>
              {candidate.note}；费用 {candidate.fee_amount} 元。
            </p>
          )}
        </>
      )}
      <form
        className="backtest-controls"
        onSubmit={(e) => {
          e.preventDefault();
          if (candidate)
            void action(() =>
              api(`${root}/signals/${signal.id}/link`, "POST", {
                curr_date: candidate.curr_date,
                entrust_no: candidate.entrust_no,
                confirmed_trade_date: date,
                confirm_plan_preceded_trade: planPreceded,
                confirmation_note: note,
              }),
            );
        }}
      >
        <label>
          实际成交日
          <input
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          券商核对依据／跳过原因
          <input
            required
            maxLength={1000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <label className="switch">
          <input type="checkbox" checked={planPreceded} onChange={(e) => setPlanPreceded(e.target.checked)} />
          已依据券商明细确认计划先于实际成交（含集合竞价）
        </label>
        <button
          disabled={
            busy || !candidate || !note.trim() || !date || !planPreceded || !!signal.skip_note
          }
        >
          确认关联该累计委托
        </button>
        <button
          type="button"
          disabled={
            busy ||
            !note.trim() ||
            !!signal.skip_note ||
            signal.execution.links.length > 0
          }
          onClick={() =>
            void action(() =>
              api(`${root}/signals/${signal.id}/skip`, "POST", { note }),
            )
          }
        >
          记录主动跳过
        </button>
      </form>
    </details>
  );
}
export default function StrategyLab({ theme }: { theme: string }) {
  const [catalog, setCatalog] = useState<LabCatalog>();
  const [history, setHistory] = useState<Batch[]>([]);
  const [batch, setBatch] = useState<Batch>();
  const [windows, setWindows] = useState<Windows>(blankWindows);
  const [scope, setScope] = useState("portfolio");
  const [period, setPeriod] = useState<Period>("development");
  const [observations, setObservations] = useState<Observation[]>([]);
  const [signals, setSignals] = useState<PlanSignal[]>([]);
  const [review, setReview] = useState<{
    id: number;
    data: ObservationReview;
  }>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function refreshActivity() {
    const [o, s] = await Promise.all([
      api<Observation[]>(`${root}/observations`),
      api<PlanSignal[]>(`${root}/signals`),
    ]);
    setObservations(o);
    setSignals(s);
  }
  async function load() {
    const [c, h] = await Promise.all([
      api<LabCatalog>(`${root}/catalog`),
      api<Batch[]>(`${root}/batches`),
    ]);
    setCatalog(c);
    setHistory(h);
    setWindows((previous) =>
      previous.development_start ? previous : (c.suggested ?? blankWindows),
    );
    await refreshActivity();
  }
  useEffect(() => {
    void load()
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  async function perform(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const selectedItem = batch?.result.instruments.find(
    (row) => row.instrument_code === scope,
  );
  const result =
    scope === "portfolio"
      ? batch?.result.portfolio[period]
      : selectedItem?.periods[period];
  const tracks = result?.tracks ?? [];
  const chartAccounts = tracks.flatMap((track) => [
    { name: track.name, account: track },
    ...(track.same_exposure_benchmark
      ? [
          {
            name: `${track.name}·同暴露持有`,
            account: track.same_exposure_benchmark,
          },
        ]
      : []),
  ]);
  async function adopt(track: Track) {
    if (!batch || scope === "portfolio") return;
    await perform(async () => {
      await api(`${root}/observations`, "POST", {
        research_batch_id: batch.id,
        instrument_code: scope,
        candidate_key: track.key,
      });
      await refreshActivity();
      setNotice(
        `${scope} 已采用“${track.name}”为新观察版本；同标的旧版暂停，不下单。`,
      );
    });
  }
  return (
    <>
      <header className="page-header">
        <div>
          <h1>持仓策略研究</h1>
          <p>独立研究本金 → 主动采用观察版本 → 每日计划 → 真实执行核对</p>
        </div>
        <button disabled={busy || loading} onClick={() => void perform(load)}>
          刷新本地状态
        </button>
      </header>
      {error && (
        <div className="alert" role="alert">
          {error}
          <button disabled={busy} onClick={() => void perform(load)}>
            重试读取
          </button>
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      {loading ? (
        <div className="empty" role="status">
          正在读取持仓范围和策略闭环…
        </div>
      ) : (
        <>
          <section className="panel backtest-panel">
            <div className="panel-header">
              <div>
                <h2>当前持仓 · 固定候选研究</h2>
                <p>{catalog?.rule_note}</p>
              </div>
            </div>
            {catalog?.warnings.map((text) => (
              <div className="notice warning" key={text}>
                {text}
              </div>
            ))}
            <div className="quote-strip">
              {catalog?.items.map((item) => (
                <div key={item.instrument_code}>
                  <span>
                    {item.instrument_code} · {item.instrument_name}
                  </span>
                  <strong>
                    研究 {number(catalog.initial_cash_per_etf)} 元
                  </strong>
                  <span>
                    真实 {number(item.actual_quantity)}份／可用{" "}
                    {number(item.available_quantity)}份
                  </span>
                  <span>
                    持仓 {item.holding_date} · 行情 {item.last_date ?? "缺失"}
                  </span>
                  <span>
                    权益核验 {item.source_checked_through ?? "缺失"}
                  </span>
                  <span>
                    60日趋势
                    {item.factors?.trend_above_ma60 == null
                      ? "缺失"
                      : item.factors.trend_above_ma60
                        ? "成立"
                        : "不成立"}
                    {" · "}20日含息动量{" "}
                    {percent(item.factors?.momentum20 ?? null)}
                  </span>
                  <span>
                    20日年化波动 {percent(item.factors?.volatility20 ?? null)} ·
                    指标截止 {item.factors?.as_of ?? "缺失"}
                  </span>
                  {item.factor_warning && <span>{item.factor_warning}</span>}
                  {item.factors && (
                    <span title={`${item.factors.source}；${item.factors.note}`}>
                      因子来源：本地行情／现金分红
                    </span>
                  )}
                </div>
              ))}
            </div>
            <p className="panel-footer">
              固定候选不做指标加权：MA20／MA60控制持有状态，正20日动量只确认新入场，波动仅供观察。半资金为25000元策略资金加25000元零息储备。
            </p>
            {!catalog?.items.length && (
              <div className="empty">
                请先在投资复盘完整同步账户，当前没有可研究的正持仓ETF。
              </div>
            )}
            <form
              className="panel-header backtest-controls"
              onSubmit={(e) => {
                e.preventDefault();
                void perform(async () => {
                  const value = await api<Batch>(
                    `${root}/batches`,
                    "POST",
                    windows,
                  );
                  setBatch(value);
                  setScope("portfolio");
                  const h = await api<Batch[]>(`${root}/batches`);
                  setHistory(h);
                });
              }}
            >
              {(
                [
                  ["development_start", "开发起始"],
                  ["development_end", "开发截止"],
                  ["validation_start", "验证起始"],
                  ["validation_end", "验证截止"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="date"
                    required
                    value={windows[key]}
                    onChange={(e) =>
                      setWindows({ ...windows, [key]: e.target.value })
                    }
                  />
                </label>
              ))}
              <button
                className="primary"
                disabled={busy || !catalog?.items.length}
              >
                {busy ? "处理中…" : "运行全部候选并保存批次"}
              </button>
            </form>
            <div className="chart-toolbar">
              <label>
                历史批次{" "}
                <select
                  disabled={busy}
                  value={batch?.id ?? ""}
                  onChange={(e) => {
                    if (e.target.value)
                      void perform(async () => {
                        setBatch(
                          await api<Batch>(`${root}/batches/${e.target.value}`),
                        );
                        setScope("portfolio");
                      });
                  }}
                >
                  <option value="">选择冻结研究批次</option>
                  {history.map((row) => (
                    <option key={row.id} value={row.id}>
                      #{row.id} · {stamp(row.created_at)} ·{" "}
                      {row.input.instruments.length}只ETF
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="panel-footer">
              佣金万一、免五、单边滑点5基点；收盘决策、次交易日开盘模拟执行。开发与验证独立账户，验证并非开发仓位延续。半资金方案保留一半零息储备，并与同暴露持有比较。
            </div>
          </section>
          {batch && (
            <section className="panel backtest-panel">
              <div className="panel-header">
                <h2>批次 #{batch.id} · 收益与风险取舍</h2>
                <label>
                  对象
                  <select
                    value={scope}
                    onChange={(e) => setScope(e.target.value)}
                  >
                    <option value="portfolio">等研究本金组合</option>
                    {batch.result.instruments.map((item) => (
                      <option
                        key={item.instrument_code}
                        value={item.instrument_code}
                      >
                        {item.instrument_code} · {item.instrument_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  区间
                  <select
                    value={period}
                    onChange={(e) => setPeriod(e.target.value as Period)}
                  >
                    <option value="development">开发区间</option>
                    <option value="validation">验证区间</option>
                  </select>
                </label>
              </div>
              <p className="panel-footer">
                {batch.input[`${period}_start`]} ～{" "}
                {batch.input[`${period}_end`]} · 范围冻结于
                {batch.input.holdings_as_of} ·
                非支配表示收益与回撤取舍，不是推荐。
              </p>
              <details className="backtest-assumptions">
                <summary>研究口径与适用边界</summary>
                {batch.result.warnings.map((text) => <p key={text}>{text}</p>)}
              </details>
              {result?.status !== "available" && (
                <div className="alert">
                  {result?.reason ?? "该区间有失败项，不能完整比较或采用。"}
                  {result?.failures?.map((row) => (
                    <p key={row.key}>
                      {row.name}：{row.reason}
                    </p>
                  ))}
                </div>
              )}
              <AccountChart theme={theme} accounts={chartAccounts} />
              {tracks
                .filter((track) => track.same_exposure_benchmark)
                .map((track) => (
                  <p className="panel-footer" key={`${track.key}-baseline`}>
                    {track.name}：总收益 {percent(track.metrics.total_return)}
                    ，最大回撤 {percent(track.metrics.max_drawdown)}；
                    同暴露买入持有：总收益{" "}
                    {percent(
                      track.same_exposure_benchmark!.metrics.total_return,
                    )}
                    ，最大回撤{" "}
                    {percent(
                      track.same_exposure_benchmark!.metrics.max_drawdown,
                    )}
                    。 两者都保留未投资的零息储备，以总研究本金核算。
                  </p>
                ))}
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>候选</th>
                      <th>总收益</th>
                      <th>最大回撤</th>
                      <th>年化波动</th>
                      <th>最长水下交易日</th>
                      <th>在场时间</th>
                      <th>完整／未平轮次</th>
                      <th>换手</th>
                      <th>佣金／滑点成本（元）</th>
                      <th>观察选择</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tracks.map((track) => (
                      <tr key={track.key}>
                        <td>
                          {track.name}
                          {result?.pareto_keys?.includes(track.key) &&
                            " · 非支配"}
                        </td>
                        <td>{percent(track.metrics.total_return)}</td>
                        <td>{percent(track.metrics.max_drawdown)}</td>
                        <td>{percent(track.metrics.annual_volatility)}</td>
                        <td>
                          {track.diagnostics?.longest_underwater_days ?? "—"}
                        </td>
                        <td>
                          {percent(track.diagnostics?.time_in_market ?? null)}
                        </td>
                        <td>
                          {track.diagnostics
                            ? `${track.diagnostics.completed_rounds}／${track.diagnostics.open_rounds}`
                            : "—"}
                        </td>
                        <td>{percent(track.metrics.turnover)}</td>
                        <td>
                          {number(track.metrics.commission)}／
                          {number(track.metrics.slippage_cost)}
                        </td>
                        <td>
                          {scope === "portfolio" ? (
                            "请选单只ETF"
                          ) : (
                            <button
                              disabled={
                                busy ||
                                selectedItem?.periods.development.status !==
                                  "available" ||
                                selectedItem?.periods.validation.status !==
                                  "available"
                              }
                              onClick={() => void adopt(track)}
                            >
                              采用此候选观察
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {tracks.some((row) => row.diagnostics?.sample_warning) && (
                <p className="panel-footer">
                  轮次限制：{[...new Set(tracks.map((row) => row.diagnostics?.sample_warning).filter(Boolean))].join("；")}。
                </p>
              )}
              <details className="backtest-assumptions">
                <summary>模拟完整退出轮次核对</summary>
                {tracks.map((track) => (
                  <div key={track.key}>
                    <h3>{track.name}</h3>
                    {!track.diagnostics?.rounds?.length ? (
                      <p>
                        {scope === "portfolio"
                          ? "组合仅汇总各ETF轮次，请选择单只ETF核对逐轮盈亏。"
                          : "暂无完整退出轮次；末尾未平仓不计入完整轮次盈亏。"}
                      </p>
                    ) : (
                      <>
                        <p>
                          完整轮次合计净盈亏{" "}
                          {number(
                            track.diagnostics.rounds.reduce(
                              (sum, round) => sum + Number(round.pnl),
                              0,
                            ),
                          )}{" "}
                          元（含买卖佣金与期间权益分红，滑点已计入价格）。
                        </p>
                        {track.diagnostics.rounds.map((round, index) => (
                          <p key={index}>
                            {round.entry_date} 入场 → {round.exit_date} 退出 ·
                            净盈亏 {number(round.pnl)} 元
                          </p>
                        ))}
                      </>
                    )}
                  </div>
                ))}
              </details>
              <p className="panel-footer">
                水下按权益历史峰值计算，轮次为模拟完整退出。研究净值不是真实持仓收益，点击采用才建立观察版本。
              </p>
            </section>
          )}
          <section className="panel backtest-panel">
            <div className="panel-header">
              <h2>观察版本</h2>
            </div>
            {!observations.length && (
              <div className="empty">
                尚未主动采用候选，不会自动建立实盘策略。
              </div>
            )}
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>标的／版本</th>
                    <th>规则／批次</th>
                    <th>采用时间</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.instrument_code} · #{row.id}
                      </td>
                      <td>
                        {row.rule.name} · 规则版本{" "}
                        {row.rule.strategy_version ?? "未记录"} · 批次#
                        {row.research_batch_id}
                        <p>
                          {Object.entries(row.rule.parameters)
                            .map(
                              ([key, value]) =>
                                `${({ window: "趋势窗口", momentum_window: "动量窗口" } as Record<string, string>)[key] ?? key} ${value}`,
                            )
                            .join("，") || "无参数"}
                        </p>
                      </td>
                      <td>{stamp(row.created_at)}</td>
                      <td>{row.active ? "观察中" : "已暂停"}</td>
                      <td>
                        <button
                          disabled={busy}
                          onClick={() =>
                            void perform(async () =>
                              setReview({
                                id: row.id,
                                data: await api<ObservationReview>(
                                  `${root}/observations/${row.id}/review`,
                                ),
                              }),
                            )
                          }
                        >
                          采用后重算
                        </button>
                        {row.active && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              void perform(async () => {
                                await api(
                                  `${root}/observations/${row.id}/pause`,
                                  "POST",
                                );
                                await refreshActivity();
                              })
                            }
                          >
                            暂停
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {review && (
              <>
                <div className="notice">
                  <strong>
                    观察#{review.id} · {review.data.label}
                  </strong>
                  <p>
                    采用 {stamp(review.data.adopted_at)} · 数据截止{" "}
                    {review.data.data_cutoff ?? "尚无"}
                  </p>
                  {review.data.reason && <p>{review.data.reason}</p>}
                </div>
                {review.data.result && (
                  <AccountChart
                    theme={theme}
                    accounts={[
                      {
                        name: "采用后规则重算",
                        account: review.data.result.strategy,
                      },
                      {
                        name: "同暴露持有重算",
                        account: review.data.result.benchmark,
                      },
                    ]}
                  />
                )}
              </>
            )}
          </section>
          <section className="panel backtest-panel">
            <div className="panel-header">
              <div>
                <h2>每日计划与真实执行</h2>
                <p>计划不等于委托或成交；买入须自行核对资金，不自动下单。</p>
              </div>
              <button
                disabled={busy || !observations.some((row) => row.active)}
                onClick={() =>
                  void perform(async () => {
                    const value = await api<{
                      created: PlanSignal[];
                      existing: PlanSignal[];
                      blocked: { instrument_code?: string; reason: string }[];
                    }>(`${root}/signals/generate`, "POST");
                    setNotice(
                      `新建${value.created.length}条，已有${value.existing.length}条。${value.blocked.map((row) => `${row.instrument_code ?? "生成阻断"}：${row.reason}`).join("；")}`,
                    );
                    await refreshActivity();
                  })
                }
              >
                生成下一执行日计划
              </button>
            </div>
            {!signals.length && (
              <div className="empty">
                暂无计划。采用观察版本后生成，行情、权益、持仓或时点不足会显示阻断原因。
              </div>
            )}
            {signals.map((signal) => (
              <article key={signal.id} className="backtest-assumptions">
                <div className="panel-header">
                  <div>
                    <h3>
                      {signal.instrument_code} · {signal.execution_date} ·{" "}
                      {
                        (
                          { buy: "买入", sell: "卖出", hold: "保持" } as Record<
                            string,
                            string
                          >
                        )[signal.plan.action]
                      }
                    </h3>
                    <span className="muted">
                      计划#{signal.id} · 观察#{signal.observation_id} · 生成{" "}
                      {stamp(signal.generated_at)} · 数据截止{" "}
                      {signal.data_cutoff}
                    </span>
                  </div>
                  <strong>
                    {executionNames[signal.execution.status] ?? "待核对"}
                  </strong>
                </div>
                <div className="quote-strip">
                  <div>
                    <span>实际／可用份额</span>
                    <strong>
                      {number(signal.plan.actual_quantity)}／
                      {number(signal.plan.available_quantity)}
                    </strong>
                    <span>持仓 {signal.plan.holding_date}</span>
                  </div>
                  <div>
                    <span>研究目标／可调整</span>
                    <strong>
                      {number(signal.plan.target_quantity)}／
                      {number(signal.plan.planned_quantity)}份
                    </strong>
                    <span>
                      应调整 {number(signal.plan.requested_quantity)}份
                    </span>
                  </div>
                  <div>
                    <span>人工关联累计成交</span>
                    <strong>
                      {number(signal.execution.confirmed_quantity)}份
                    </strong>
                    <span>
                      {signal.plan.funding_check_required
                        ? "待核对可用现金"
                        : "无新增买入资金需求"}
                    </span>
                  </div>
                </div>
                <p>
                  {signal.plan.reason} · 参考收盘 {signal.plan.reference_price}{" "}
                  元，非可成交报价。
                </p>
                {signal.plan.position_basis && (
                  <p>目标份额依据：{signal.plan.position_basis}</p>
                )}
                <details className="backtest-assumptions">
                  <summary>生成时指标与证据</summary>
                  {signal.plan.factors ? (
                    <>
                      <p>
                        指标截止 {signal.plan.factors.as_of} · 60日趋势
                        {signal.plan.factors.trend_above_ma60 == null
                          ? "缺失"
                          : signal.plan.factors.trend_above_ma60
                            ? "成立"
                            : "不成立"}{" "}
                        · 20日含息动量 {percent(signal.plan.factors.momentum20)}{" "}
                        · 20日年化波动{" "}
                        {percent(signal.plan.factors.volatility20)}
                      </p>
                      <p>
                        {signal.plan.factors.source}；{signal.plan.factors.note}
                      </p>
                    </>
                  ) : (
                    <p>该计划未记录背景因子。</p>
                  )}
                  {Object.entries(signal.plan.indicators ?? {}).map(
                    ([key, value]) => (
                      <p key={key}>
                        {(
                          {
                            signal_index: "含息信号指数",
                            moving_average: "规则均线",
                            momentum: "入场确认动量",
                          } as Record<string, string>
                        )[key] ?? key}
                        ：
                        {value == null
                          ? "缺失"
                          : key === "momentum"
                            ? percent(Number(value))
                            : number(value)}
                      </p>
                    ),
                  )}
                  <p className="backtest-hash">
                    输入证据摘要：{signal.plan.input_sha256 ?? "未记录"}
                  </p>
                </details>
                {signal.plan.warnings.map((text) => (
                  <p key={text} className="notice warning">
                    {text}
                  </p>
                ))}
                {signal.skip_note && <p>跳过原因：{signal.skip_note}</p>}
                {signal.execution.links.map((link) => (
                  <p key={link.id}>
                    已关联委托 {link.entrust_no} · 确认成交日{" "}
                    {link.confirmed_trade_date} · 当前累计
                    {number(link.current_amount)}份 · 依据：
                    {link.confirmation_note}
                    {link.source_revised && (
                      <strong> · 来源已修订，须核对</strong>
                    )}
                    {!link.source_valid && (
                      <strong> · 来源无效，未计入数量</strong>
                    )}
                  </p>
                ))}
                {signal.plan.action !== "hold" && !signal.skip_note && (
                  <ExecutionForm
                    signal={signal}
                    refresh={refreshActivity}
                    report={setError}
                  />
                )}
              </article>
            ))}
          </section>
        </>
      )}
    </>
  );
}
