import { useEffect, useState } from "react";
import EtfFactorChart from "../components/EtfFactorChart";
import ChartCaption from "../components/ChartCaption";
import { api, type Candle, type Instrument } from "../lib/api";
import { chartStamp } from "../lib/chart";

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
  const [history, setHistory] = useState<Candle[]>([]);
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
    api<Candle[]>(`/candles/${code}?start=1990-01-01&end=${end}`)
      .then((data) => {
        if (active) setHistory(data);
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
  const rows = history.filter(row => row.date >= start && row.date <= end);
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
          <p>日 K 与成交量 · 本地历史行情</p>
        </div>
        <button onClick={goJobs}>采集与调度</button>
      </header>
      <section className="panel research-chart-panel">
        <div className="panel-header chart-heading">
          <div className="research-context">
            <h2>{item?.name ?? code}</h2>
            <label className="compact-selector">研究标的
              <select aria-label="行情标的" value={code} onChange={(e) => setCode(e.target.value)}>
                {instruments.map((i) => <option key={i.code} value={i.code}>{i.code} · {i.name}</option>)}
              </select>
            </label>
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
              ["近一月", 30],
              ["近三月", 90],
              ["近半年", 180],
              ["近一年", 365],
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
            <ChartCaption
              title={`${code} · 日线 · 前复权展示`}
              meta={`${start} ~ ${end} · 均线 MA5/10/20/30/60（按前复权收盘计算） · 顶底确认使用因果复权价格 · 来源：${item?.source === "ChatBI" ? "财通证券历史日行情（ChatBI）" : item?.source ?? "财通证券历史日行情"} · 生成：${chartStamp()}`}
            />
            <EtfFactorChart history={history} start={start} end={end} theme={theme} instrumentCode={code} />
          </>
        )}
        <div className="panel-footer">
          来源：财通证券历史日行情　·　最新入库行情日：
          <span className="mono">{item?.last_date ?? "—"}</span>
          　·　成交量额保留源数值，单位待数据源确认；价格图使用前复权 OHLC。
        </div>
      </section>
    </>
  );
}
