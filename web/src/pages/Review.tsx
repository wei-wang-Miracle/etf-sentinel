import { useEffect, useMemo, useState } from "react";
import EtfReview from "../components/EtfReview";
import { api, stamp } from "../lib/api";
import {
  entrustStatusName,
  syncStatusName,
  type AccountEntrusts,
  type AccountHoldings,
  type AccountSyncStatus,
  type AccountSyncSummary,
} from "../lib/account";

const today = () =>
  new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" });
function daysAgo(days: number) {
  const value = new Date(`${today()}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}
const number = (value: number | null | undefined, digits = 2) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const quantity = (value: number | null | undefined) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
const signed = (value: number | null | undefined) =>
  value == null ? "—" : `${value > 0 ? "+" : ""}${number(value)}`;
const pnlClass = (value: number | null | undefined) =>
  value == null ? "" : value > 0 ? "market-up" : value < 0 ? "market-down" : "";

export default function Review({ theme }: { theme: string }) {
  const [syncStatus, setSyncStatus] = useState<AccountSyncStatus | null>(null);
  const [holdings, setHoldings] = useState<AccountHoldings | null>(null);
  const [trades, setTrades] = useState<AccountEntrusts | null>(null);
  const [start, setStart] = useState(daysAgo(30));
  const [end, setEnd] = useState(today());
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(true);
  const [tradeLoading, setTradeLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [notice, setNotice] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      api<AccountSyncStatus>("/account/sync/status"),
      api<AccountHoldings>("/account/holdings"),
    ])
      .then(([status, rows]) => {
        if (!active) return;
        setSyncStatus(status);
        setHoldings(rows);
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [refresh]);

  useEffect(() => {
    if (!start || !end || start > end) {
      setTradeLoading(false);
      return;
    }
    let active = true;
    setTradeLoading(true);
    setTradeError("");
    const params = new URLSearchParams({ start, end, limit: "500" });
    if (code) params.set("instrument_code", code);
    api<AccountEntrusts>(`/account/entrusts?${params.toString()}`)
      .then((rows) => {
        if (active) setTrades(rows);
      })
      .catch((e) => {
        if (active) setTradeError((e as Error).message);
      })
      .finally(() => {
        if (active) setTradeLoading(false);
      });
    return () => {
      active = false;
    };
  }, [start, end, code, refresh]);

  async function sync() {
    setSyncing(true);
    setError("");
    setNotice("");
    try {
      const result = await api<AccountSyncSummary>("/account/sync", "POST");
      setNotice(
        `同步完成：抓取 ${result.fetched_count} 行，入库 ${result.stored_count} 行，跳过非配置 ${result.skipped_count} 行。`,
      );
      setRefresh((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  const latest = syncStatus?.latest;
  const summary = holdings?.summary;
  const codeOptions = useMemo(() => {
    const map = new Map<string, string>();
    holdings?.items.forEach((item) =>
      map.set(item.instrument_code, item.instrument_name),
    );
    trades?.items.forEach((item) =>
      map.set(item.instrument_code, item.instrument_name),
    );
    return [...map.entries()];
  }, [holdings, trades]);

  return (
    <>
      <header className="page-header">
        <div>
          <h1>投资复盘</h1>
          <p>配置内 ETF 实盘持仓与成交 · 本地账户数据</p>
        </div>
        <div className="review-actions">
          <button className="primary" disabled={syncing} onClick={() => void sync()}>
            {syncing ? "同步中…" : "同步持仓与成交"}
          </button>
          <button disabled={syncing} onClick={() => setRefresh((value) => value + 1)}>
            刷新本地数据
          </button>
        </div>
      </header>

      <div className="notice">
        本页只展示当前 20 只配置内 ETF；账户内其他 ETF、LOF、逆回购和现金未纳入，
        不能据此计算全账户收益。
      </div>
      {error && (
        <div className="alert" role="alert">
          {error}
          <button onClick={() => setRefresh((value) => value + 1)}>重试</button>
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}

      <section className="panel review-status-panel">
        <div className="panel-header">
          <h2>同步状态</h2>
          <span className="muted">账户接口 · 增量窗口同步</span>
        </div>
        {latest ? (
          <>
            <div className="quote-strip">
              <div>
                <span>状态</span>
                <strong>
                  <span className={`badge ${latest.status}`}>
                    {syncStatusName[latest.status] ?? latest.status}
                  </span>
                </strong>
              </div>
              <div>
                <span>最近开始</span>
                <strong className="mono">{stamp(latest.started_at)}</strong>
              </div>
              <div>
                <span>抓取 / 入库</span>
                <strong>
                  {latest.fetched_count} / {latest.stored_count}
                </strong>
              </div>
              <div>
                <span>跳过非配置</span>
                <strong>{latest.skipped_count}</strong>
              </div>
              <div>
                <span>错误行</span>
                <strong>{latest.error_count}</strong>
              </div>
              <div>
                <span>同步区间</span>
                <strong className="mono">
                  {latest.range_start ?? "—"} ~ {latest.range_end ?? "—"}
                </strong>
              </div>
            </div>
            {latest.error_message && (
              <div className="notice warning">{latest.error_message}</div>
            )}
          </>
        ) : (
          <div className="empty" role="status">
            尚未同步账户数据。
            <button className="primary" disabled={syncing} onClick={() => void sync()}>
              首次同步
            </button>
          </div>
        )}
      </section>

      <EtfReview theme={theme} />
      <section className="panel review-panel">
        <div className="panel-header">
          <h2>
            配置内持仓 <span className="muted">/ {summary?.holding_count ?? 0}</span>
          </h2>
          <span className="muted">数据截止 {holdings?.as_of ?? "—"}</span>
        </div>
        <div className="quote-strip">
          <div>
            <span>配置内市值</span>
            <strong>{number(summary?.market_value)}</strong>
          </div>
          <div>
            <span>成本金额</span>
            <strong>{number(summary?.cost_value)}</strong>
          </div>
          <div>
            <span>未实现盈亏</span>
            <strong className={pnlClass(summary?.unrealized_pnl)}>
              {signed(summary?.unrealized_pnl)}
            </strong>
          </div>
          <div>
            <span>当前持仓</span>
            <strong>{summary?.holding_count ?? 0} 只</strong>
          </div>
        </div>
        {loading && !holdings ? (
          <div className="empty" role="status">
            正在读取本地账户数据…
          </div>
        ) : holdings?.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>代码 / 名称</th>
                  <th className="number">当前 / 可用</th>
                  <th className="number">成本价</th>
                  <th className="number">最新收盘</th>
                  <th className="number">市值</th>
                  <th className="number">成本金额</th>
                  <th className="number">未实现盈亏</th>
                  <th className="number">权重</th>
                  <th>数据日期</th>
                </tr>
              </thead>
              <tbody>
                {holdings.items.map((item) => (
                  <tr key={item.instrument_code}>
                    <td>
                      <strong className="mono">{item.instrument_code}</strong>
                      <span className="subtext">{item.instrument_name}</span>
                    </td>
                    <td className="number">
                      {quantity(item.current_amount)}
                      <span className="subtext">可用 {quantity(item.enable_amount)}</span>
                    </td>
                    <td className="number">{number(item.cost_price, 3)}</td>
                    <td className="number">
                      {number(item.latest_close, 3)}
                      <span className="subtext">
                        {item.latest_close_date ?? "无本地收盘"}
                      </span>
                    </td>
                    <td className="number">{number(item.market_value)}</td>
                    <td className="number">{number(item.cost_value)}</td>
                    <td className={`number ${pnlClass(item.unrealized_pnl)}`}>
                      {signed(item.unrealized_pnl)}
                    </td>
                    <td className="number">
                      {item.weight == null ? "—" : `${(item.weight * 100).toFixed(2)}%`}
                    </td>
                    <td className="mono">{item.data_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <h2>尚无配置内持仓</h2>
            <p>运行一次同步，读取当前持仓和成交记录。</p>
            <button className="primary" disabled={syncing} onClick={() => void sync()}>
              立即同步
            </button>
          </div>
        )}
        <div className="panel-footer">
          市值按本地最近收盘计算；无本地收盘的持仓不在市值中伪造。只覆盖配置内 ETF。
        </div>
      </section>

      <section className="panel review-panel">
        <div className="panel-header">
          <h2>
            委托与成交 <span className="muted">/ {trades?.count ?? 0}</span>
          </h2>
          <span className="muted">默认最近 30 天 · 最多 500 行</span>
        </div>
        <div className="chart-toolbar review-filters">
          <label>
            起始
            <input
              aria-label="成交起始日期"
              type="date"
              value={start}
              max={end}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            截止
            <input
              aria-label="成交截止日期"
              type="date"
              value={end}
              min={start}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
          <label>
            ETF
            <select
              aria-label="成交 ETF 筛选"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            >
              <option value="">全部配置内 ETF</option>
              {codeOptions.map(([value, name]) => (
                <option key={value} value={value}>
                  {value} · {name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {tradeError && (
          <div className="alert" role="alert">
            {tradeError}
            <button onClick={() => setRefresh((value) => value + 1)}>重试</button>
          </div>
        )}
        {tradeLoading ? (
          <div className="empty" role="status">
            正在读取委托与成交…
          </div>
        ) : trades?.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>日期 / 时间</th>
                  <th>代码 / 名称</th>
                  <th>方向</th>
                  <th className="number">委托</th>
                  <th className="number">成交</th>
                  <th className="number">费用</th>
                  <th>状态</th>
                  <th className="number">撤单</th>
                </tr>
              </thead>
              <tbody>
                {trades.items.map((item) => (
                  <tr key={`${item.curr_date}-${item.entrust_no}`}>
                    <td className="mono">
                      {item.curr_date}
                      <span className="subtext">{item.display_time ?? "—"}</span>
                    </td>
                    <td>
                      <strong className="mono">{item.instrument_code}</strong>
                      <span className="subtext">{item.instrument_name}</span>
                    </td>
                    <td>
                      <span
                        className={`badge ${
                          item.side === "buy" ? "buy" : item.side === "sell" ? "sell" : ""
                        }`}
                      >
                        {item.side === "buy" ? "买入" : item.side === "sell" ? "卖出" : item.side}
                      </span>
                    </td>
                    <td className="number">
                      {quantity(item.entrust_amount)}{" "}
                      <span className="subtext">@ {number(item.entrust_price, 3)}</span>
                    </td>
                    <td className="number">
                      {item.business_amount > 0 ? quantity(item.business_amount) : "—"}{" "}
                      {item.business_amount > 0 && (
                        <span className="subtext">@ {number(item.business_price, 3)}</span>
                      )}
                    </td>
                    <td className="number">{number(item.fee_amount)}</td>
                    <td>
                      <span className="badge">{entrustStatusName(item)}</span>
                      <span className="subtext">源状态 {item.entrust_status ?? "—"}</span>
                    </td>
                    <td className="number">
                      {item.withdraw_amount > 0 ? quantity(item.withdraw_amount) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">所选区间没有配置内委托记录。</div>
        )}
        <div className="panel-footer">
          费用为成交金额与清算金额差额的推导值，不是券商逐笔费用明细；方向、状态和撤单保留源字段。
        </div>
      </section>
    </>
  );
}
