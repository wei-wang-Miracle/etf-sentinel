import { useCallback, useEffect, useState } from "react";
import BacktestChart from "../components/BacktestChart";
import { api, stamp } from "../lib/api";
import {
  experimentParameters,
  parameterSummary,
  percent,
  type Catalog,
  type Experiment,
  type Result,
} from "../lib/backtests";

export default function Backtests({ theme }: { theme: string }) {
  const [catalog, setCatalog] = useState<Catalog>();
  const [code, setCode] = useState("510500");
  const [strategy, setStrategy] = useState("ma_trend");
  const [parameters, setParameters] = useState<Record<string, number>>({
    window: 60,
  });
  const [start, setStart] = useState("2025-01-01");
  const [end, setEnd] = useState("");
  const [cash, setCash] = useState("100000");
  const [rate, setRate] = useState("0.0001");
  const [minimum, setMinimum] = useState("5");
  const [slip, setSlip] = useState("5");
  const [run, setRun] = useState<Result>();
  const [history, setHistory] = useState<Experiment[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [tradeIndex, setTradeIndex] = useState(0);
  const selectTrade = useCallback((index: number) => setTradeIndex(index), []);
  const rule = catalog?.strategies.find((s) => s.key === strategy);
  const instrument = catalog?.instruments.find(
    (i) => i.instrument_code === code,
  );
  const load = useCallback(async () => {
    const [data, experiments] = await Promise.all([
      api<Catalog>("/backtests/catalog"),
      api<Experiment[]>("/backtests"),
    ]);
    setCatalog(data);
    setHistory(experiments);
    return data;
  }, []);
  useEffect(() => {
    load()
      .then((data) => setEnd(data.instruments[0]?.last_date ?? ""))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [load]);
  async function execute() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<Result>("/backtests", "POST", {
        instrument_code: code,
        strategy_key: strategy,
        parameters,
        start_date: start,
        end_date: end,
        initial_cash: cash,
        commission_rate: rate,
        minimum_commission: minimum,
        slippage_bps: slip,
      });
      setRun(result);
      setTradeIndex(0);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api("/backtests/sources/refresh", "POST");
      await load();
      setNotice("两只基金的分红资料已更新，旧实验保持原快照。");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function restore(id: string) {
    if (!id) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<Result>(`/backtests/${id}`);
      setRun(result);
      setTradeIndex(0);
      setCode(result.instrument_code);
      setStrategy(result.strategy_key);
      setParameters(experimentParameters(result));
      setStart(String(result.settings.start_date));
      setEnd(String(result.settings.end_date));
      setCash(String(result.settings.initial_cash));
      setRate(String(result.settings.commission_rate));
      setMinimum(String(result.settings.minimum_commission));
      setSlip(String(result.settings.slippage_bps));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function verify() {
    if (!run) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ identical: boolean }>(
        `/backtests/${run.id}/verify`,
        "POST",
      );
      setNotice(
        result.identical
          ? "快照复算一致：逐日账户、成交、费用和绩效与原实验相同。"
          : "复算结果不一致，请检查引擎与输入快照。",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const account = run?.result.strategy;
  const metrics = account?.metrics;
  const trade = account?.trades[tradeIndex];
  const number = (value: string | number) =>
    Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return (
    <>
      <header className="page-header">
        <div>
          <h1>策略回测</h1>
          <p>同一账户核算，比较择时规则与买入持有</p>
        </div>
        <button disabled={busy || loading} onClick={refresh}>
          更新分红资料
        </button>
      </header>
      <section className="panel backtest-panel">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void execute();
          }}
        >
          <div className="panel-header backtest-controls">
            <label>
              研究标的
              <select
                value={code}
                onChange={(e) => setCode(e.target.value)}
                disabled={busy}
              >
                {catalog?.instruments.map((i) => (
                  <option key={i.instrument_code} value={i.instrument_code}>
                    {i.instrument_code} · {i.instrument_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              规则
              <select
                value={strategy}
                onChange={(e) => {
                  setStrategy(e.target.value);
                  setParameters(
                    Object.fromEntries(
                      (
                        catalog?.strategies.find(
                          (s) => s.key === e.target.value,
                        )?.parameters ?? []
                      ).map((p) => [p.key, p.default]),
                    ),
                  );
                }}
              >
                {catalog?.strategies.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            {rule?.parameters.map((p) => (
              <label key={p.key}>
                {p.label}
                <input
                  type="number"
                  min={p.min}
                  max={p.max}
                  required
                  value={parameters[p.key] ?? p.default}
                  onChange={(e) =>
                    setParameters({
                      ...parameters,
                      [p.key]: Number(e.target.value),
                    })
                  }
                />
              </label>
            ))}
            <label>
              起始
              <input
                type="date"
                required
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              截止
              <input
                type="date"
                required
                value={end}
                max={instrument?.last_date ?? undefined}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <button
              className="primary"
              type="submit"
              disabled={busy || loading || !catalog}
            >
              {busy ? "处理中…" : "运行并保存"}
            </button>
          </div>
          <details className="backtest-assumptions">
            <summary>
              成交假设：初始 {number(cash)} 元，佣金{" "}
              {(Number(rate) * 10000).toFixed(2)}‱、最低 {minimum} 元，单边滑点{" "}
              {slip} 基点
            </summary>
            <div className="backtest-controls">
              <label>
                初始资金（元）
                <input
                  type="number"
                  min="1000"
                  max="100000000"
                  step="0.01"
                  required
                  value={cash}
                  onChange={(e) => setCash(e.target.value)}
                />
              </label>
              <label>
                佣金率（小数）
                <input
                  type="number"
                  min="0"
                  max="0.01"
                  step="0.00001"
                  required
                  value={rate}
                  onChange={(e) => setRate(e.target.value)}
                />
              </label>
              <label>
                最低佣金（元）
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  required
                  value={minimum}
                  onChange={(e) => setMinimum(e.target.value)}
                />
              </label>
              <label>
                单边滑点（基点）
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  required
                  value={slip}
                  onChange={(e) => setSlip(e.target.value)}
                />
              </label>
            </div>
            <p>
              以上为可修改的研究假设。收盘决策，次日开盘成交，买入整手100份；分红按登记、除息、发放核算，现金不自动再投；期末不强平。开盘价加固定不利滑点作为成交假设，不以当天高低价反推成交；缺少停牌资料，发现零成交量时整段拒绝回测。未模拟涨跌停排队和容量。
            </p>
          </details>
        </form>
        <div className="chart-toolbar">
          <span className="muted">
            {instrument?.count ?? 0} 个本地交易日 · 分红资料读取日{" "}
            {instrument?.source_checked_through ?? "尚未采集"}
          </span>
          <label className="compact-selector">
            已存实验
            <select
              aria-label="已存实验"
              value={run?.id ?? ""}
              disabled={busy}
              onChange={(e) => void restore(e.target.value)}
            >
              <option value="">选择历史实验</option>
              {history.map((h) => (
                <option key={h.id} value={h.id}>
                  #{h.id} · {h.instrument_code} ·{" "}
                  {parameterSummary(h, catalog?.strategies)} · 引擎
                  {h.engine_version} · {h.actual_start}～{h.actual_end}
                </option>
              ))}
            </select>
          </label>
        </div>
        {run && catalog && run.engine_version !== catalog.engine_version && (
          <div className="notice warning" role="status">
            该实验使用旧版引擎 {run.engine_version}，当前为{" "}
            {catalog.engine_version}
            。请使用当前版本重新运行后再作比较；旧快照保留供追溯。
          </div>
        )}
        {error && (
          <div className="alert" role="alert">
            {error}{" "}
            <button
              onClick={() => {
                setError("");
                setLoading(true);
                load()
                  .catch((e) => setError(e.message))
                  .finally(() => setLoading(false));
              }}
            >
              重新读取
            </button>
          </div>
        )}
        {notice && (
          <div className="notice" role="status">
            {notice}
          </div>
        )}
        {loading ? (
          <div className="empty chart-empty" role="status">
            正在读取策略与数据覆盖…
          </div>
        ) : !run ? (
          <div className="empty chart-empty">
            <h2>先把一条规则算清楚</h2>
            <p>{rule?.description}</p>
            <p>
              选择区间后运行，开始日前需保留足够交易日预热；缺日或分红校验失败会停止计算。
            </p>
          </div>
        ) : (
          <>
            <div className="panel-header">
              <div>
                <h2>
                  {run.instrument_code} ·{" "}
                  {catalog?.strategies.find((s) => s.key === run.strategy_key)
                    ?.name ?? "已保存规则"}{" "}
                  · {parameterSummary(run, catalog?.strategies)}
                </h2>
                <span className="muted">
                  已存实验 #{run.id}　{run.actual_start} ～ {run.actual_end}　
                  {stamp(run.created_at)}
                </span>
              </div>
              <button disabled={busy} onClick={verify}>
                复算原快照
              </button>
            </div>
            <div className="quote-strip">
              <div>
                <span>策略总收益</span>
                <strong
                  className={
                    (metrics?.total_return ?? 0) >= 0
                      ? "market-up"
                      : "market-down"
                  }
                >
                  {percent(metrics?.total_return ?? null)}
                </strong>
              </div>
              <div>
                <span>买入持有收益</span>
                <strong>
                  {percent(run.result.benchmark.metrics.total_return)}
                </strong>
              </div>
              <div>
                <span>收益差（百分点）</span>
                <strong>
                  {(
                    (metrics!.total_return -
                      run.result.benchmark.metrics.total_return) *
                    100
                  ).toFixed(2)}
                </strong>
              </div>
              <div>
                <span>策略最大回撤</span>
                <strong>{percent(metrics?.max_drawdown ?? null)}</strong>
              </div>
              <div>
                <span>模拟成交 / 佣金</span>
                <strong>
                  {metrics?.trade_count} 笔 / {number(metrics!.commission)} 元
                </strong>
              </div>
              <div>
                <span>滑点价差成本</span>
                <strong>{number(metrics!.slippage_cost)} 元</strong>
              </div>
            </div>
            <BacktestChart run={run} theme={theme} onTrade={selectTrade} />
            <div className="backtest-trade-note">
              {trade ? (
                <>
                  <label>
                    成交解释
                    <select
                      aria-label="成交解释"
                      value={tradeIndex}
                      onChange={(e) => setTradeIndex(Number(e.target.value))}
                    >
                      {account?.trades.map((t, i) => (
                        <option key={i} value={i}>
                          {t.trade_date} · {t.side === "buy" ? "买入" : "卖出"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p>
                    {trade.signal_date} 收盘：{trade.reason}。{trade.trade_date}{" "}
                    开盘模拟{trade.side === "buy" ? "买入" : "卖出"}{" "}
                    {trade.quantity} 份，成交价 {trade.price} 元，佣金{" "}
                    {trade.commission} 元，滑点成本 {trade.slippage_cost} 元。
                  </p>
                </>
              ) : (
                <p>该规则在本区间没有模拟成交。</p>
              )}
            </div>
            <details className="backtest-assumptions">
              <summary>
                本次口径与来源 · 引擎 {run.engine_version} / 规则{" "}
                {run.strategy_version} · 预热 {run.warmup_count} 日
              </summary>
              <p>
                保存参数：资金 {number(String(run.settings.initial_cash))}{" "}
                元，佣金率 {String(run.settings.commission_rate)}、最低{" "}
                {String(run.settings.minimum_commission)} 元，滑点{" "}
                {String(run.settings.slippage_bps)} 基点。年化收益{" "}
                {percent(metrics!.annual_return)}（不足一年不展示），年化波动{" "}
                {percent(metrics!.annual_volatility)}。期末权益{" "}
                {number(metrics!.final_equity)} 元。
              </p>
              <p>
                行情：{run.provenance.market_source}，截止 {run.data_cutoff}
                。权益：
                <a
                  href={run.provenance.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  东方财富分红送配
                </a>
                ，读取于 {stamp(run.provenance.collected_at)}。
                {run.calendar_version}
                。权益为公开二手来源，结合复权因子交叉检查，未逐条核对基金公司公告。
              </p>
              <p>
                信号使用当时收盘与除息现金构造的含息指数及均线；该指数假设除息再投，实际账户按分红发放日收盘收到现金，次交易日开盘才可使用；非交易日发放则下个交易日开盘可用。原始价格成交，不用未知口径复权价。无杠杆、无自动下单；未模拟盘口排队、容量冲击和全部交易所限制。
              </p>
              <p className="backtest-hash">输入摘要：{run.input_sha256}</p>
            </details>
          </>
        )}
        <div className="panel-footer">
          仅作历史研究。买入持有使用相同资金、费用、分红和成交规则；图中买卖为模拟记录。不同参数与数据快照属于不同实验。
        </div>
      </section>
    </>
  );
}
