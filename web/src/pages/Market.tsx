import { useEffect, useState } from "react";
import KLine from "../components/KLine";
import { api, type Candle, type Instrument } from "../lib/api";

const today = () =>
  new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
function daysAgo(days: number) {
  const value = new Date(`${today()}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
}
const number = (value: number | undefined, digits = 3) =>
  value == null
    ? "—"
    : value.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

export default function Market({
  theme,
  goJobs,
}: {
  theme: string;
  goJobs: () => void;
}) {
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [code, setCode] = useState("510500");
  const [start, setStart] = useState(daysAgo(365));
  const [end, setEnd] = useState(daysAgo(1));
  const [rows, setRows] = useState<Candle[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    api<Instrument[]>("/instruments")
      .then(setInstruments)
      .catch((e) => setError(e.message));
  }, [retry]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    if (!start || !end || start > end) {
      setError("请选择有效的起止日期");
      setLoading(false);
      return;
    }
    api<Candle[]>(`/candles/${code}?start=${start}&end=${end}`)
      .then((data) => {
        if (active) setRows(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [code, start, end, retry]);
  const item = instruments.find((i) => i.code === code);
  const last = rows.at(-1);
  const changeClass =
    last?.change_pct == null
      ? ""
      : last.change_pct >= 0
        ? "market-up"
        : "market-down";
  return (
    <>
      <header className="page-header">
        <div>
          <h1>行情展示</h1>
          <p>观察历史走势，从同一份本地数据开始研究</p>
        </div>
        <span className="badge info">历史日行情 · 非实时</span>
      </header>
      <div className="instrument-chips">
        {(instruments.length
          ? instruments
          : ["510500", "512100", "159531", "159205", "588080"].map((code) => ({
              code,
              name: "名称待采集",
            }))
        ).map((i) => (
          <button
            className={`instrument-chip ${i.code === code ? "active" : ""}`}
            key={i.code}
            onClick={() => setCode(i.code)}
          >
            <strong className="mono">{i.code}</strong>
            <span>{i.name}</span>
          </button>
        ))}
      </div>
      <section className="panel">
        <div className="panel-header chart-heading">
          <div>
            <h2>{item?.name ?? code}</h2>
            <span className="muted mono">{code} · 日K · 原始价格</span>
          </div>
          <div className="date-controls">
            <label>
              起始{" "}
              <input
                aria-label="行情起始日期"
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              截止{" "}
              <input
                aria-label="行情截止日期"
                type="date"
                value={end}
                max={daysAgo(1)}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>
        </div>
        <div className="chart-toolbar">
          <div className="range-buttons">
            {[
              ["1M", 30],
              ["3M", 90],
              ["6M", 180],
              ["1Y", 365],
              ["全部", 0],
            ].map(([name, days]) => (
              <button
                key={name}
                onClick={() => {
                  setStart(
                    days
                      ? daysAgo(Number(days))
                      : (item?.first_date ?? item?.start_date ?? "2020-01-01"),
                  );
                  setEnd(daysAgo(1));
                }}
              >
                {name}
              </button>
            ))}
          </div>
          <span className="muted">红涨绿跌 · 价格轴非零起点</span>
        </div>
        {error ? (
          <div className="empty" role="alert">
            <p>{error}</p>
            <button onClick={() => setRetry((n) => n + 1)}>重试</button>
          </div>
        ) : loading ? (
          <div className="empty chart-empty" role="status">
            正在读取本地日行情…
          </div>
        ) : !rows.length ? (
          <div className="empty chart-empty">
            <h2>该区间没有行情数据</h2>
            <p>调整日期范围，或先采集标的的历史日行情。</p>
            <button className="primary" onClick={goJobs}>
              前往定时任务
            </button>
          </div>
        ) : (
          <>
            <div className="quote-strip">
              <div>
                <span>区间末日收盘</span>
                <strong className={changeClass}>{number(last?.close)}</strong>
              </div>
              <div>
                <span>涨跌幅</span>
                <strong className={changeClass}>
                  {last?.change_pct == null
                    ? "—"
                    : `${last.change_pct >= 0 ? "+" : ""}${number(last.change_pct, 2)}%`}
                </strong>
              </div>
              <div>
                <span>开盘</span>
                <strong>{number(last?.open)}</strong>
              </div>
              <div>
                <span>最高 / 最低</span>
                <strong>
                  {number(last?.high)} / {number(last?.low)}
                </strong>
              </div>
              <div>
                <span>行情日期</span>
                <strong>{last?.date}</strong>
              </div>
            </div>
            <KLine rows={rows} theme={theme} />
          </>
        )}
        <div className="panel-footer">
          来源：ChatBI / daily_ohlcv_etf　·　最新入库行情日：
          <span className="mono">{item?.last_date ?? "—"}</span>
          　·　成交量额保留源数值，单位待数据源确认；未推断复权口径。
        </div>
      </section>
      {!loading && !error && rows.length > 0 && (
        <section className="panel">
          <div className="panel-header">
            <h2>日行情明细</h2>
            <span className="muted">
              最近 20 个交易日 / 区间共 {rows.length} 条
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th className="number">开盘</th>
                  <th className="number">最高</th>
                  <th className="number">最低</th>
                  <th className="number">收盘</th>
                  <th className="number">涨跌幅</th>
                  <th className="number">成交量（源单位）</th>
                  <th>源更新时间</th>
                </tr>
              </thead>
              <tbody>
                {rows
                  .slice(-20)
                  .reverse()
                  .map((r) => (
                    <tr key={r.date}>
                      <td className="mono">{r.date}</td>
                      {[r.open, r.high, r.low, r.close].map((v, i) => (
                        <td key={i} className="number">
                          {number(v)}
                        </td>
                      ))}
                      <td
                        className={`number ${r.change_pct == null ? "" : r.change_pct >= 0 ? "market-up" : "market-down"}`}
                      >
                        {r.change_pct == null
                          ? "—"
                          : `${r.change_pct >= 0 ? "+" : ""}${number(r.change_pct, 2)}%`}
                      </td>
                      <td className="number">{number(r.volume, 0)}</td>
                      <td className="mono">{r.source_updated_at ?? "—"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
