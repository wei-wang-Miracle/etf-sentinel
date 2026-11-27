import { useEffect, useState } from "react";
import { api, type Instrument } from "../lib/api";

function InstrumentRow({
  item,
  refresh,
}: {
  item: Instrument;
  refresh: () => void;
}) {
  const [enabled, setEnabled] = useState(item.enabled);
  const [start, setStart] = useState(item.start_date);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);
  const dirty = enabled !== item.enabled || start !== item.start_date;
  useEffect(() => {
    setEnabled(item.enabled);
    setStart(item.start_date);
  }, [item]);
  async function save() {
    setBusy(true);
    setMessage("");
    setFailed(false);
    try {
      await api(`/instruments/${item.code}`, "PUT", {
        enabled,
        start_date: start,
      });
      setMessage("已保存");
      refresh();
    } catch (e) {
      setFailed(true);
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <tr>
      <td>
        <strong className="mono">{item.code}</strong>
        <span className="subtext">{item.name}</span>
      </td>
      <td>
        <label className="switch">
          <input
            type="checkbox"
            aria-label={`${item.code}启用采集`}
            checked={enabled}
            onChange={(e) => {
              setEnabled(e.target.checked);
              setMessage("");
            }}
          />
          {enabled ? "启用" : "停用"}
        </label>
      </td>
      <td>
        <input
          type="date"
          aria-label={`${item.code}历史起始日期`}
          value={start}
          onChange={(e) => {
            setStart(e.target.value);
            setMessage("");
          }}
        />
      </td>
      <td className="number">{item.count.toLocaleString()}</td>
      <td className="mono">
        {item.first_date ?? "—"}
        <span className="subtext">至 {item.last_date ?? "—"}</span>
      </td>
      <td>
        <span className={`badge ${item.count ? "success" : "warning"}`}>
          {item.count ? "已有历史数据" : "尚未采集"}
        </span>
      </td>
      <td>
        <button disabled={!dirty || busy || !start} onClick={save}>
          {busy ? "保存中" : "保存"}
        </button>
        {message && (
          <span
            className={`subtext ${failed ? "danger-text" : "success-text"}`}
            role={failed ? "alert" : "status"}
          >
            {message}
          </span>
        )}
      </td>
    </tr>
  );
}

export default function Instruments({ embedded = false }: { embedded?: boolean }) {
  const [rows, setRows] = useState<Instrument[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  async function load() {
    setError("");
    try {
      setRows(await api("/instruments"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const keyword = search.trim().toLowerCase();
  const visibleRows = rows.filter((item) =>
    `${item.code}${item.name}`.toLowerCase().includes(keyword),
  );
  return (
    <>
      <header className="page-header">
        <div>
          {embedded ? <h2>标的配置</h2> : <h1>标的配置</h1>}
          <p>管理研究范围与历史行情采集边界</p>
        </div>
        <button onClick={load}>刷新状态</button>
      </header>
      <div className="notice">
        国家队 18 只基金 已纳入统一研究范围。停用只停止后续采集，已有行情保留；调整起始日期后，在定时任务页运行采集。
      </div>
      {error && (
        <div className="alert" role="alert">
          {error}
          <button onClick={load}>重试</button>
        </div>
      )}
      <section className="panel">
        <div className="panel-header">
          <h2>
            研究标的 <span className="muted">/ {visibleRows.length}{keyword ? `（共 ${rows.length}）` : ""}</span>
          </h2>
          <div className="date-controls">
            <label className="search-field">
              <span className="sr-only">筛选标的</span>
              <input
                type="search"
                aria-label="筛选标的"
                placeholder="筛选代码或名称"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <span className="muted">数据源：财通证券 · 历史日行情</span>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>代码 / 名称</th>
                <th>采集状态</th>
                <th>历史起始日期</th>
                <th className="number">入库条数</th>
                <th>行情覆盖区间</th>
                <th>数据状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((item) => (
                <InstrumentRow key={item.code} item={item} refresh={load} />
              ))}
            </tbody>
          </table>
        </div>
        {!loading && !error && rows.length > 0 && !visibleRows.length && (
          <div className="empty">
            没有匹配的标的。<button onClick={() => setSearch("")}>清除筛选</button>
          </div>
        )}
        {loading && (
          <div className="empty" role="status">
            正在读取标的配置…
          </div>
        )}
        {!loading && !error && !rows.length && (
          <div className="empty">尚未初始化标的，请检查数据库迁移。</div>
        )}
      </section>
      <footer className="footnote">
        名称由数据源返回后更新。采集起点早于上市日时，空响应会保留查询记录，不生成虚拟行情。
      </footer>
    </>
  );
}
