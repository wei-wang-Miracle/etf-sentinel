import { useEffect, useState } from "react";
import { api, stamp, type Instrument } from "../lib/api";
import { syncStatusName, type AccountSyncStatus, type AccountSyncSummary } from "../lib/account";
import Instruments from "./Instruments";
import Jobs from "./Jobs";
import Tabs from "../components/Tabs";
import AppLink from "../components/AppLink";
import { useResearchQuery } from "../lib/research";
import { safeReturnUrl } from "../lib/navigation";

export default function DataManagement({ initialTab = "instruments" }: { initialTab?: string }) {
  const [query, update] = useResearchQuery({ manage: initialTab, code: "", return_to: "" });
  const tab = ["instruments", "account", "jobs"].includes(query.manage) ? query.manage : "instruments";
  const returnTo = safeReturnUrl(query.return_to);
  return <>
    <header className="page-header"><div><h1>数据管理</h1><p>检查采集覆盖、账户同步与任务运行，数据缺失不会按零参与研究。</p></div>{returnTo && <AppLink className="button-link" href={returnTo}>返回原任务{query.code ? ` · ${query.code}` : ""}</AppLink>}</header>
    <Tabs label="数据管理分类" items={[["instruments", "标的配置"], ["account", "账户与权益"], ["jobs", "任务与运行记录"]].map(([value, label]) => ({ value, label }))} value={tab} onChange={(manage) => update({ manage })}>
      {tab === "jobs" ? <Jobs /> : tab === "account" ? <DataPreparation key={query.code} initialCode={query.code} /> : <Instruments embedded />}
    </Tabs>
  </>;
}
function DataPreparation({ initialCode }: { initialCode: string }) {
  const [status, setStatus] = useState<AccountSyncStatus>();
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [code, setCode] = useState(initialCode);
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  async function load() {
    const [data, items] = await Promise.all([api<AccountSyncStatus>("/account/sync/status"), api<Instrument[]>("/instruments")]);
    setStatus(data); setInstruments(items); setCode((old) => old || items[0]?.code || "");
  }
  useEffect(() => { void load().catch((e) => setError(e.message)).finally(() => setLoading(false)); }, []);
  async function prepare(kind: "account" | "actions") {
    setBusy(true); setError(""); setNotice("");
    try {
      if (kind === "account") {
        const result = await api<AccountSyncSummary>("/account/sync", "POST");
        setNotice(`账户同步：${syncStatusName[result.status] ?? result.status}，保存 ${result.stored_count} 条。${result.error_message ?? ""}`);
      } else {
        await api(`/backtests/sources/refresh?instrument_code=${code}`, "POST");
        setNotice(`${code} 分红权益已核验。历史回测仍保留原快照。`);
      }
      await load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <section className="panel journey-inset"><h2>账户与分红权益准备</h2><p className="muted">外部账户接口只读，本地保存配置内 ETF 的持仓与累计委托；不访问或操作券商交易。每日信号会检查依赖是否就绪。</p>
    {error && <p className="alert" role="alert">{error}<button onClick={() => void load().then(() => setError("")).catch((e) => setError(e.message))}>重试</button></p>}{notice && <p className="notice" role="status">{notice}</p>}
    {loading ? <p className="empty">正在读取同步状态…</p> : <><p>最近同步：{status?.latest ? `${syncStatusName[status.latest.status] ?? status.latest.status} · ${stamp(status.latest.ended_at)}` : "尚未同步"}</p><div className="preparation-grid"><section><h3>真实账户同步</h3><p className="muted">保存完整持仓与累计委托；空持仓快照保持为空。</p><div className="journey-actions"><button className="primary" disabled={busy || status?.latest?.status === "running"} onClick={() => void prepare("account")}>{busy ? "处理中…" : "同步真实持仓与成交"}</button></div></section><section><h3>单 ETF 分红权益</h3><p className="muted">仅更新所选标的权益资料，不修改历史回测快照。</p><div className="journey-actions"><label>ETF<select value={code} onChange={(e) => setCode(e.target.value)} disabled={busy}>{instruments.map((row) => <option key={row.code} value={row.code}>{row.code} · {row.name}</option>)}</select></label><button disabled={busy || !code} onClick={() => void prepare("actions")}>更新这只 ETF 的分红权益</button></div></section></div>
    <div className="journey-history">{status?.runs.map((run) => <p key={run.id}>#{run.id} · {syncStatusName[run.status] ?? run.status} · {run.range_start ?? "—"}—{run.range_end ?? "—"} · {stamp(run.ended_at)}{run.error_message ? ` · ${run.error_message}` : ""}</p>)}</div></>}
  </section>;
}
