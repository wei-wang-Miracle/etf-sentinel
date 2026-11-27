import { useEffect } from "react";
import type { Instrument } from "../lib/api";
import type { AccountHoldings } from "../lib/account";
import { useResearchQuery } from "../lib/research";
import { useApiResource } from "../lib/useApiResource";
import { journeyUrl, type JourneyCatalog } from "../lib/strategyJourney";
import { dataManagementUrl } from "../lib/navigation";
import AppLink from "../components/AppLink";
import Tabs from "../components/Tabs";
import DailySignals from "../components/DailySignals";
import EtfReview from "../components/EtfReview";
import ResearchObject, { type ResearchSummary } from "./ResearchObject";

const details = [{ value: "overview", label: "行情与背景" }, { value: "operations", label: "真实操作" }, { value: "signals", label: "每日信号" }];

export default function MyEtfs({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({ code: "", object: "", detail: "overview", scope: "held", search: "", start: "", end: "" });
  const instruments = useApiResource<Instrument[]>("/instruments");
  const holdings = useApiResource<AccountHoldings>("/account/holdings");
  const catalog = useApiResource<JourneyCatalog>(!query.code && !query.object || query.detail === "signals" ? "/strategies/catalog" : null);
  const legacyIndex = query.object.startsWith("index:");
  const code = legacyIndex ? query.object.slice(6) : query.code || (query.object.startsWith("etf:") ? query.object.slice(4) : "");
  const summary = useApiResource<ResearchSummary>(code ? `/research/object?object_type=${legacyIndex ? "index" : "etf"}&code=${encodeURIComponent(code)}` : null);
  useEffect(() => {
    if (summary.data?.redirected_from) update({ code: summary.data.object.code, object: `etf:${summary.data.object.code}`, tab: "valuation", detail: "overview", legacy_index: code }, { history: "replace" });
  }, [summary.data]);
  const detail = details.some((item) => item.value === query.detail) ? query.detail : "overview";
  const scope = query.scope === "all" ? "all" : "held";
  const positionsKnown = !!holdings.data?.as_of && !holdings.error && !holdings.loading;
  const held = new Set(positionsKnown ? holdings.data!.items.filter((row) => row.current_amount > 0).map((row) => row.instrument_code) : []);
  const keyword = query.search.trim().toLowerCase();
  const list = (instruments.data ?? []).filter((row) => (scope === "all" || held.has(row.code)) && `${row.code}${row.name}`.toLowerCase().includes(keyword));
  const name = summary.data?.object.name || instruments.data?.find((row) => row.code === code)?.name || code;
  const dates = { ...(query.start ? { start: query.start } : {}), ...(query.end ? { end: query.end } : {}) };
  const listUrl = journeyUrl("etfs", undefined, { scope, search: query.search, ...dates });
  const strategyUrl = journeyUrl("strategies", code, { view: "backtest", ...dates });

  if (code) return <div className="etf-dossier">
    <header className="object-header">
      <div className="object-heading"><AppLink className="back-link" href={listUrl}>我的 ETF</AppLink><span className="muted">/</span><h1>{name}</h1><span className="mono object-code">{code}</span></div>
      <div className="object-actions"><label className="object-selector">切换 ETF<select aria-label="当前 ETF" value={legacyIndex ? "" : code} onChange={(event) => update({ code: event.target.value, object: `etf:${event.target.value}`, legacy_index: "", edit: "" })}>
        {!instruments.data?.some((item) => item.code === code) && <option value={legacyIndex ? "" : code}>{legacyIndex ? "正在定位关联 ETF" : code}</option>}
        {instruments.data?.map((item) => <option key={item.code} value={item.code}>{item.code} · {item.name}</option>)}
      </select></label>{detail === "overview" && <AppLink className="button-link" href={journeyUrl("etfs", code, { auxiliary: "compare", ...dates })}>横向对比</AppLink>}{detail === "signals" && <AppLink className="button-link" href={journeyUrl("strategies", code, dates)}>管理策略</AppLink>}<AppLink className="button-link primary" href={strategyUrl}>回测算法</AppLink></div>
      <div className="evidence-strip"><span>{!positionsKnown ? holdings.loading ? "持仓读取中" : holdings.error ? "持仓状态未取得" : "尚未同步持仓" : held.has(code) ? "当前持仓" : "当前未持仓"}</span><span>行情截至 <span className="mono">{summary.data?.summary.price.as_of ?? "—"}</span></span><span>持仓快照 <span className="mono">{holdings.error ? "未取得" : holdings.data?.as_of ?? "—"}</span></span><span>历史日频 · 非实时</span></div>
    </header>
    {legacyIndex ? <p className="empty" role="status">{summary.error || "正在定位指数关联的 ETF…"}</p> : <Tabs label="ETF详情" items={details} value={detail} onChange={(detail) => update({ detail })}>
      {detail === "overview" ? <ResearchObject theme={theme} code={code} summary={summary.data} loading={summary.loading} error={summary.error} retry={summary.retry} />
        : detail === "operations" ? <EtfReview key={code} theme={theme} fixedObject /> : <DailySignals key={code} code={code} catalog={catalog} />}
    </Tabs>}
  </div>;

  return <>
    <header className="page-header"><div><h1>我的 ETF</h1><p>从一只 ETF 开始，查看证据、研究方法与每日信号。</p></div><AppLink className="button-link" href={journeyUrl("etfs", undefined, { auxiliary: "compare", ...dates })}>跨 ETF 对比</AppLink></header>
    <DailySignals compact catalog={catalog} />
    <section className="etf-directory" aria-labelledby="etf-directory-title">
      <div className="directory-toolbar"><div><h2 id="etf-directory-title">研究范围</h2><p className="muted">仅含配置内 ETF · 持仓快照 <span className="mono">{holdings.error ? "未取得" : holdings.data?.as_of ?? "尚未同步"}</span></p></div>
        <div className="directory-filters"><div className="segmented" role="group" aria-label="ETF范围"><button aria-pressed={scope === "held"} onClick={() => update({ scope: "held" })}>当前持仓</button><button aria-pressed={scope === "all"} onClick={() => update({ scope: "all" })}>全部 ETF</button></div>
          <label className="search-field"><span className="sr-only">搜索 ETF</span><input type="search" aria-label="搜索 ETF" placeholder="代码或名称" value={query.search} onChange={(event) => update({ search: event.target.value })} /></label></div>
      </div>
      {holdings.error && <p className="notice warning" role="alert">持仓状态未取得：{holdings.error}。仍可切换全部 ETF 研究。<button onClick={holdings.retry}>重试持仓</button><AppLink href={dataManagementUrl("account")}>检查账户同步</AppLink></p>}
      {catalog.error && <p className="notice warning" role="alert">策略状态未取得，ETF 行情仍可查看。<button onClick={catalog.retry}>重试策略状态</button></p>}
      {instruments.error && <p className="alert" role="alert">标的读取失败：{instruments.error}<button onClick={instruments.retry}>重试标的</button></p>}
      {instruments.loading || (scope === "held" && holdings.loading) ? <div className="empty skeleton-state" role="status">正在读取 ETF 与持仓状态…</div>
        : !instruments.data?.length && !instruments.error ? <div className="empty"><h3>尚无配置内 ETF</h3><AppLink href={dataManagementUrl("instruments")}>检查标的配置</AppLink></div>
          : scope === "held" && !positionsKnown ? <div className="empty"><h3>{holdings.error ? "持仓状态未取得" : "尚未同步持仓"}</h3><p>先同步账户，或切换全部 ETF 开始研究。</p><button onClick={() => update({ scope: "all" })}>查看全部 ETF</button></div>
            : scope === "held" && !held.size ? <div className="empty"><h3>暂无当前持仓</h3><p>当前完整快照中没有正持仓，可研究未持仓 ETF。</p><button onClick={() => update({ scope: "all" })}>查看全部 ETF</button></div>
              : <div className="journey-etf-list"><div className="directory-columns" aria-hidden="true"><span>ETF 名称与代码</span><span>持仓状态</span><span>策略状态</span><span>行情截至</span><span>操作</span></div>
                {list.map((row) => { const active = catalog.data?.assignments.find((assignment) => assignment.active && assignment.instrument_code === row.code); const marketUrl = journeyUrl("etfs", row.code, { scope, search: query.search, detail: "overview", tab: "price", ...dates }); return <article key={row.code} className="journey-etf-row">
                  <AppLink className="etf-name" href={marketUrl}><strong>{row.name}</strong><span className="mono">{row.code}</span></AppLink>
                  <span className="holding-label">{!positionsKnown ? holdings.loading ? "持仓读取中" : holdings.error ? "持仓状态未取得" : "尚未同步" : held.has(row.code) ? "当前持仓" : "当前未持仓"}</span>
                  <span>{catalog.loading ? "策略读取中" : catalog.error ? "策略状态未取得" : active ? <AppLink href={journeyUrl("etfs", row.code, { scope, search: query.search, detail: "signals", ...dates })}>{catalog.data?.strategies.find((item) => item.id === active.strategy_id)?.name ?? "已启用策略"}</AppLink> : "未启用策略"}</span>
                  <span className="mono">{row.last_date ?? "暂无行情"}</span>
                  <div className="row-actions"><AppLink className="button-link" href={marketUrl}>查看行情</AppLink></div>
                </article>; })}
                {!list.length && !instruments.error && <div className="empty"><h3>没有匹配的 ETF</h3><p>请调整代码或名称。</p><button onClick={() => update({ search: "" })}>清除搜索</button></div>}
              </div>}
    </section>
  </>;
}
