import { useEffect, useState, type FormEvent } from "react";
import AppLink from "../components/AppLink";
import { api, type Instrument } from "../lib/api";
import { dataManagementUrl } from "../lib/navigation";
import { journeyUrl } from "../lib/strategyJourney";

type InstrumentPreview = {
  code: string;
  market_verified: boolean;
  market_name: string | null;
  market_row_count: number;
  already_configured: boolean;
  funddb_profile: {
    fund_name: string | null;
    fund_full_name: string | null;
    category_primary: string | null;
    category_tag: string | null;
    tracking_index_code: string | null;
    tracking_index_name: string | null;
    index_corr: number | null;
    setup_date: string | null;
    management_fee_pct: number | null;
    custody_fee_pct: number | null;
    linked_otc_code: string | null;
  } | null;
  suggested_index_exists: boolean;
  national_team_covered: boolean;
  warnings: string[];
};

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
        {item.catalog_profile && <span className="subtext">{[item.catalog_profile.category_tag, item.catalog_profile.management_fee_pct == null ? null : `费率 ${item.catalog_profile.management_fee_pct}%+${item.catalog_profile.custody_fee_pct ?? "—"}%`, item.catalog_profile.mapped_index_code ? `关联指数 ${item.catalog_profile.mapped_index_code}` : item.catalog_profile.tracking_index_code ? `源跟踪 ${item.catalog_profile.tracking_index_code}` : "未映射指数"].filter(Boolean).join(" · ")}</span>}
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
        <span className="subtext"><AppLink href={journeyUrl("etfs", item.code, { scope: "all", tab: "price" })}>查看因子</AppLink></span>
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
  const [code, setCode] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState("");
  const [added, setAdded] = useState<{ code: string; run_id: number | null }>();
  const [preview, setPreview] = useState<InstrumentPreview>();
  const [confirmIndexLink, setConfirmIndexLink] = useState(false);
  const [mappingEvidence, setMappingEvidence] = useState("");
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
  async function previewCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAdding(true);
    setAdded(undefined);
    setAddError("");
    setPreview(undefined);
      setConfirmIndexLink(false);
    setMappingEvidence("");
    try {
      const result = await api<InstrumentPreview>(`/instruments/preview/${code}`);
      setPreview(result);
      setConfirmIndexLink(!!result.funddb_profile?.tracking_index_code && result.suggested_index_exists);
    } catch (e) {
      setAddError((e as Error).message);
    } finally {
      setAdding(false);
    }
  }
  async function add() {
    if (!preview) return;
    setAdding(true);
    setAdded(undefined);
    setAddError("");
    try {
      const payload = confirmIndexLink
        ? {
          code: preview.code,
          confirm_index_link: true,
          tracking_index_code: preview.funddb_profile?.tracking_index_code,
          mapping_evidence: mappingEvidence,
        }
        : { code: preview.code };
      const result = await api<{ code: string; run_id: number | null }>("/instruments", "POST", {
        ...payload,
      });
      setAdded(result);
      setCode("");
      setPreview(undefined);
      setSearch(result.code);
      await load();
    } catch (e) {
      setAddError((e as Error).message);
    } finally {
      setAdding(false);
    }
  }
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
      {added && (
        <div className="notice" role="status">
          {added.code} 已新增，{added.run_id === null ? "采集任务正在运行，本标的将在下次运行时纳入" : `已启动采集与核验（#${added.run_id}）`}
          <AppLink href={dataManagementUrl("jobs", "etf", added.code)}>查看采集记录</AppLink>
        </div>
      )}
      {addError && <div className="alert" role="alert">{addError}</div>}
      {error && (
        <div className="alert" role="alert">
          {error}
          <button onClick={load}>重试</button>
        </div>
      )}
      <section className="panel">
        <div className="panel-header">
          <form className="date-controls" onSubmit={previewCode}>
            <label>ETF 代码
              <input className="mono" type="text" inputMode="numeric" pattern="[0-9]{6}" size={8}
                maxLength={6} required value={code} disabled={adding} onChange={(e) => setCode(e.target.value)} />
            </label>
            <button className="primary" type="submit" disabled={adding}>{adding ? "核验中…" : "核验并预览"}</button>
          </form>
        </div>
        {preview && (
          <div className="notice instrument-preview" role="status">
            <div><strong className="mono">{preview.code}</strong> 已通过近30日行情核验（{preview.market_row_count} 条）{preview.market_name ? ` · ${preview.market_name}` : ""}</div>
            {preview.funddb_profile ? <div className="preview-grid">
              <span>FundDB档案：{preview.funddb_profile.fund_full_name ?? preview.funddb_profile.fund_name ?? "—"}</span>
              <span>分类：{[preview.funddb_profile.category_primary, preview.funddb_profile.category_tag].filter(Boolean).join(" · ") || "—"}</span>
              <span>建议指数：{preview.funddb_profile.tracking_index_name ?? "—"} <span className="mono">{preview.funddb_profile.tracking_index_code ?? ""}</span>{preview.funddb_profile.index_corr == null ? "" : ` · 相关度 ${preview.funddb_profile.index_corr.toFixed(3)}`}</span>
              <span>指数估值池：{preview.suggested_index_exists ? "已纳入，可复用现有估值采集" : "未纳入，本次不会自动加入"} · 国家队覆盖：{preview.national_team_covered ? "已覆盖" : "未覆盖"}</span>
            </div> : null}
            {preview.warnings.map((warning) => <p className="muted" key={warning}>{warning}</p>)}
            {preview.funddb_profile?.tracking_index_code && preview.suggested_index_exists && !preview.already_configured && <label className="switch"><input type="checkbox" checked={confirmIndexLink} onChange={(event) => setConfirmIndexLink(event.target.checked)} />同时建立已核验指数关联</label>}
            {confirmIndexLink && <label>关联依据<input aria-label="指数关联依据" value={mappingEvidence} onChange={(event) => setMappingEvidence(event.target.value)} placeholder="例如基金合同与指数代码核验" required /></label>}
            {preview.already_configured ? <p>该 ETF 已在研究范围内，无需重复新增。</p> : <button className="primary" type="button" onClick={add} disabled={adding || (confirmIndexLink && !mappingEvidence.trim())}>{adding ? "新增中…" : "确认新增 ETF"}</button>}
          </div>
        )}
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
          <div className="empty">尚无研究标的。</div>
        )}
      </section>
      <footer className="footnote">
        停用只停止后续行情采集，已有行情保留。采集起点早于上市日时，空响应只保留查询记录。
      </footer>
    </>
  );
}
