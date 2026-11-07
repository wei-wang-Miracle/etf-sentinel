import { useEffect, useRef, useState } from "react";
import { api, type Candle, type Instrument } from "../lib/api";
import { dateAgo, number, useResearchQuery } from "../lib/research";
import ChartCaption from "./ChartCaption";
import KLine from "./KLine";
import ResearchChart from "./ResearchChart";

type Actual = {
  status: string;
  reasons?: string[];
  net_pnl?: string;
  realized_pnl?: string;
  unrealized_pnl?: string;
  fees?: string;
  dividends_paid?: string;
  final_receivable?: string;
  xirr?: number | null;
  xirr_status?: string;
  cashflow_start?: string;
  cashflow_end?: string;
  dividend_note?: string;
  input_sha256: string;
  daily?: { trade_date: string; net_pnl: string; quantity: string }[];
};
type Result = {
  actual: Actual;
  start: string;
  end: string;
  markers: {
    trade_date: string;
    side: string;
    quantity: string;
    price: string;
  }[];
  quality: {
    issues: string[];
    snapshot_date: string | null;
    market_date: string | null;
    source_checked_through: string | null;
    quantity_delta: string | null;
  };
  comparability: string;
};
type Research = {
  tracks: {
    name: string;
    daily: { trade_date: string; nav: number; drawdown: number }[];
    metrics: {
      total_return: number;
      max_drawdown: number;
      time_in_market: number;
      turnover: number;
      commission: string;
    };
  }[];
  experiment_ids: number[];
  note: string;
};

export default function EtfReview({ theme, fixedObject = false }: { theme: string; fixedObject?: boolean }) {
  const researchGeneration = useRef(0);
  const [query, update] = useResearchQuery({
    code: "510500",
    start: dateAgo(180),
    end: dateAgo(1),
  });
  const { code, start, end } = query;
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [candlesError, setCandlesError] = useState("");
  const [research, setResearch] = useState<Research | null>(null);
  const [confirmOpening, setConfirmOpening] = useState(false),
    [confirmDates, setConfirmDates] = useState(false);
  const [cash, setCash] = useState("50000"),
    [rate, setRate] = useState("0.0001"),
    [minimum, setMinimum] = useState("0"),
    [slippage, setSlippage] = useState("5");
  const [error, setError] = useState(""),
    [researchError, setResearchError] = useState("");
  const [loading, setLoading] = useState(true),
    [running, setRunning] = useState(false);
  const [refresh, setRefresh] = useState(0),
    [view, setView] = useState("nav");
  useEffect(() => {
    const controller = new AbortController();
    api<Instrument[]>("/instruments", "GET", undefined, controller.signal)
      .then(setInstruments)
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    setConfirmOpening(false);
    setConfirmDates(false);
  }, [code]);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setCandles([]);
    setCandlesError("");
    setError("");
    setLoading(true);
    if (!start || !end || start > end) {
      setError("请选择有效日期区间");
      setLoading(false);
      return;
    }
    const params = new URLSearchParams({
      start,
      end,
      confirm_zero_opening: String(confirmOpening),
      confirm_trade_dates: String(confirmDates),
    });
    Promise.allSettled([
      api<Result>(
        `/account/review/${code}?${params}`,
        "GET",
        undefined,
        controller.signal,
      ),
      api<Candle[]>(
        `/candles/${code}?start=${start}&end=${end}`,
        "GET",
        undefined,
        controller.signal,
      ),
    ])
      .then(([review, rows]) => {
        if (controller.signal.aborted) return;
        if (review.status === "fulfilled") setResult(review.value);
        else setError(review.reason.message);
        if (rows.status === "fulfilled") setCandles(rows.value);
        else setCandlesError(rows.reason.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [code, start, end, confirmOpening, confirmDates, refresh]);
  useEffect(() => {
    researchGeneration.current += 1;
    setRunning(false);
    setResearch(null);
    setResearchError("");
  }, [code, start, end, cash, rate, minimum, slippage]);
  async function run() {
    const generation = ++researchGeneration.current;
    setRunning(true);
    setResearch(null);
    setResearchError("");
    try {
      const value = await api<Research>(
        `/account/research/${code}?${new URLSearchParams({ start, end, initial_cash: cash, commission_rate: rate, minimum_commission: minimum, slippage_bps: slippage })}`,
        "POST",
      );
      if (researchGeneration.current === generation) setResearch(value);
    } catch (e) {
      if (researchGeneration.current === generation)
        setResearchError((e as Error).message);
    } finally {
      if (researchGeneration.current === generation) setRunning(false);
    }
  }
  async function refreshSource() {
    setError("");
    try {
      await api(`/backtests/sources/refresh?instrument_code=${code}`, "POST");
      setRefresh(refresh + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const actual = result?.actual;
  return (
    <section className="panel research-chart-panel integrated-research">
      <div className="panel-header">
        <h2>单 ETF 复盘</h2>
        <div className="date-controls">
          {!fixedObject && <label>
            ETF{" "}
            <select
              disabled={fixedObject}
              value={code}
              onChange={(e) => update({ code: e.target.value })}
            >
              {instruments.map((i) => (
                <option key={i.code} value={i.code}>
                  {i.code} · {i.name}
                </option>
              ))}
            </select>
          </label>}
          <label>
            起始{" "}
            <input
              type="date"
              value={start}
              onChange={(e) => update({ start: e.target.value })}
            />
          </label>
          <label>
            截止{" "}
            <input
              type="date"
              value={end}
              onChange={(e) => update({ end: e.target.value })}
            />
          </label>
        </div>
      </div>
      {result?.actual.status !== "available" && result && <p className="notice warning">{result.actual.status === "not_applicable" ? "真实核算不适用" : "真实核算暂不可计算"}：{result.actual.reasons?.join("；")}</p>}
      <div className="chart-toolbar">
        <label>
          <input
            type="checkbox"
            checked={confirmOpening}
            onChange={(e) => setConfirmOpening(e.target.checked)}
          />{" "}
          我已核实：2025-01-20 前该ETF零持仓
        </label>
        <label>
          <input
            type="checkbox"
            checked={confirmDates}
            onChange={(e) => setConfirmDates(e.target.checked)}
          />{" "}
          我已核实：累计成交属于委托日期
        </label>
        <button onClick={() => void refreshSource()}>更新本标的权益资料</button>
      </div>
      <p className="muted">
        仅在有对账依据时确认；确认只用于本次核算，不修改源数据，也不能替代同步、T+1、费用和数量检查。
      </p>
      {loading ? (
        <div className="empty" role="status">
          正在核验完整历史…
        </div>
      ) : error ? (
        <div className="notice warning" role="alert">
          {error} <button onClick={() => setRefresh(refresh + 1)}>重试</button>
        </div>
      ) : (
        result && (
          <>
            <h2>真实交易 · 项目现金流</h2>
            {actual?.status !== "available" ? (
              <div className="notice warning">
                {actual?.status === "not_applicable" ? "不适用" : "暂不可计算"}
                ：{actual?.reasons?.join("；")}
              </div>
            ) : (
              <>
                <div className="quote-strip">
                  <div>
                    <span>区间净盈亏（元）</span>
                    <strong
                      className={
                        Number(actual.net_pnl) >= 0
                          ? "market-up"
                          : "market-down"
                      }
                    >
                      {number(actual.net_pnl)}
                    </strong>
                  </div>
                  <div>
                    <span>资金加权年化收益</span>
                    <strong>
                      {actual.xirr == null
                        ? "暂不输出"
                        : `${number(actual.xirr * 100)}%`}
                    </strong>
                    <small>
                      {actual.cashflow_start} — {actual.cashflow_end} ·
                      短期年化仅作辅助
                    </small>
                  </div>
                  <div>
                    <span>推导费用（已计入，元）</span>
                    <strong>{number(actual.fees)}</strong>
                  </div>
                  <div>
                    <span>推算到账 / 期末应收（元）</span>
                    <strong>
                      {number(actual.dividends_paid)} /{" "}
                      {number(actual.final_receivable)}
                    </strong>
                  </div>
                </div>
                <p className="muted">
                  {actual.xirr_status === "available" ? "" : actual.xirr_status}{" "}
                  · {actual.dividend_note}
                </p>
                <ResearchChart
                  theme={theme}
                  unit="累计净盈亏（元，非净值）"
                  series={[
                    {
                      name: "真实项目累计净盈亏",
                      points:
                        actual.daily?.map((r) => [
                          r.trade_date,
                          Number(r.net_pnl),
                        ]) ?? [],
                    },
                  ]}
                />
                <ResearchChart
                  theme={theme}
                  unit="历史数量（份）"
                  series={[
                    {
                      name: "按完整历史重建持仓",
                      points:
                        actual.daily?.map((r) => [
                          r.trade_date,
                          Number(r.quantity),
                        ]) ?? [],
                    },
                  ]}
                />
              </>
            )}
            {candles.length > 0 && (
              <>
                <KLine rows={candles} trades={result.markers} theme={theme} />
                <p className="muted">
                  原始日K，复权口径未确认；买卖标记使用委托日，未确认成交日期前仅供核对，不代表精确成交时刻。
                </p>
              </>
            )}
            <ChartCaption
              title={`${code} · 真实项目日频复盘`}
              meta={`${result.start} 至 ${result.end} · 本地账户累计委托及财通证券收盘／公开权益 · 现金流金额非净值 · 查看时间 ${new Date().toLocaleString("zh-CN")}`}
            />
            <details>
              <summary>数据质量与核算依据</summary>
              <p>
                有效区间 {result.start} — {result.end} · 快照{" "}
                {result.quality.snapshot_date ?? "缺失"} · 行情{" "}
                {result.quality.market_date ?? "缺失"} · 权益核验{" "}
                {result.quality.source_checked_through ?? "缺失"}
              </p>
              <p>
                数量差异 {result.quality.quantity_delta ?? "未核验"} 份 ·
                输入摘要 <span className="mono">{actual?.input_sha256}</span>
              </p>
              {result.quality.issues.map((issue) => (
                <p key={issue}>{issue}</p>
              ))}
              <p>{result.comparability}</p>
            </details>
          </>
        )
      )}
      {candlesError && <p className="notice warning">日K读取失败：{candlesError}。真实核算独立保留。</p>}
      {error && candles.length > 0 && <KLine rows={candles} theme={theme} />}
      <details className="research-evidence"><summary>统一资金规则研究（模拟，与真实盈亏分开）</summary>
      <h2>统一资金规则研究</h2>
      <p className="muted">
        研究使用独立名义资金，与真实盈亏分开；买入持有、20日均线、60日均线和现金同起止。信号次日开盘执行，T+1，整手，现金零利息。
      </p>
      <div className="chart-toolbar">
        <label>
          名义资金（元）
          <input
            type="number"
            value={cash}
            min="1000"
            onChange={(e) => setCash(e.target.value)}
          />
        </label>
        <label>
          佣金费率
          <input
            type="number"
            step="0.0001"
            min="0"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
          />
        </label>
        <label>
          最低佣金（元）
          <input
            type="number"
            min="0"
            value={minimum}
            onChange={(e) => setMinimum(e.target.value)}
          />
        </label>
        <label>
          滑点（基点）
          <input
            type="number"
            min="0"
            value={slippage}
            onChange={(e) => setSlippage(e.target.value)}
          />
        </label>
        <button
          className="primary"
          disabled={running || !start || !end || start > end}
          onClick={() => void run()}
        >
          {running ? "正在核验并保存实验…" : "运行四条研究基线"}
        </button>
      </div>
      {researchError && (
        <div className="notice warning" role="alert">
          {researchError}
        </div>
      )}
      {research && (
        <>
          <div className="chart-toolbar">
            <button
              onClick={() => setView("nav")}
              aria-pressed={view === "nav"}
            >
              研究净值
            </button>
            <button
              onClick={() => setView("drawdown")}
              aria-pressed={view === "drawdown"}
            >
              研究回撤
            </button>
          </div>
          <ResearchChart
            theme={theme}
            unit={view === "nav" ? "研究净值（初始100）" : "研究回撤（%）"}
            series={research.tracks.map((track) => ({
              name: track.name,
              points: track.daily.map((row) => [
                row.trade_date,
                (view === "nav" ? row.nav : row.drawdown) * 100,
              ]),
            }))}
          />
          <div className="quote-strip">
            {research.tracks.map((track) => (
              <div key={track.name}>
                <span>{track.name}</span>
                <strong>
                  收益 {number(track.metrics.total_return * 100)}%
                </strong>
                <small>
                  回撤 {number(track.metrics.max_drawdown * 100)}% · 在场{" "}
                  {number(track.metrics.time_in_market * 100)}%
                </small>
                <small>
                  换手 {number(track.metrics.turnover)} · 佣金{" "}
                  {number(track.metrics.commission)} 元
                </small>
              </div>
            ))}
          </div>
          <p className="muted">
            {research.note} · 已保存实验 {research.experiment_ids.join("、")}
            ，可在策略回测页查看并以快照复算。仅供研究，不构成投资建议。
          </p>
        </>
      )}
      </details>
    </section>
  );
}
