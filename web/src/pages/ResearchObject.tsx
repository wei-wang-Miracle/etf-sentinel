import { useState } from "react";
import ChartCaption from "../components/ChartCaption";
import Tabs from "../components/Tabs";
import KLine from "../components/KLine";
import ValuationChart from "../components/ValuationChart";
import { type Candle } from "../lib/api";
import type { ValuationPoint } from "./IndexValuations";
import { SentimentTrend, type SentimentDaily } from "./Sentiment";
import { dateAgo, metrics, number, useResearchQuery } from "../lib/research";
import { useApiResource } from "../lib/useApiResource";
import { dataManagementUrl } from "../lib/navigation";
import { journeyUrl } from "../lib/strategyJourney";

type Metric = { value: number | null; local_percentile: number | null; source_percentile: number | null; trade_date: string | null; value_status: string };
export type ResearchSummary = {
  object: { type: string; code: string; name: string };
  linked: { index_code: string | null; national_team_tracked: boolean };
  summary: {
    price: { value: number | null; as_of: string | null; change_pct: number | null };
    valuation: { index_code: string; index_name: string; metrics: Record<string, Metric> } | null;
    national_team: { ratio: number | null; as_of: string | null };
    sentiment: { category_key: string; category_name: string; index_name?: string | null; fear_greed_score: number | null; last_date: string | null; source_label: string | null }[];
  };
  redirected_from?: { type: string; code: string } | null;
  warnings: string[];
};
type ValuationData = { series: ValuationPoint[]; candles: Candle[] };
type NationalData = { estimation_start_date: string; holdings: { trade_date: string; estimated_holding_pct: number | null }[]; candles: Candle[] };
type ReviewMarkers = { markers: { trade_date: string; side: string; quantity: string; price: string }[] };
const views = [{ value: "price", label: "行情" }, { value: "valuation", label: "关联估值" }, { value: "funds", label: "国家队" }, { value: "sentiment", label: "市场情绪" }];
const tasks: Record<string, string> = { price: "etf", valuation: "index-valuations", funds: "national-team", sentiment: "sentiment" };

export default function ResearchObject({ theme, code, summary, loading, error, retry }: {
  theme: string; code: string; summary?: ResearchSummary; loading: boolean; error: string; retry: () => void;
}) {
  const [query, update] = useResearchQuery({ tab: "price", start: dateAgo(365), end: dateAgo(1), metric: "pe", category: "", legacy_index: "" });
  const [showActual, setShowActual] = useState(false);
  const tab = views.some((item) => item.value === query.tab) ? query.tab : "price";
  const metric = metrics[query.metric] ? query.metric : "pe";
  const { start, end } = query;
  const validDates = !!start && !!end && start <= end;
  const index = summary?.linked.index_code;
  const category = summary?.summary.sentiment.find((item) => item.category_key === query.category) ?? summary?.summary.sentiment[0];
  const range = `start=${start}&end=${end}`;
  const path = !summary || !validDates ? null : tab === "price" ? `/candles/${code}?${range}`
    : tab === "valuation" ? index ? `/index-valuations/series/${index}?${range}&metric=${metric}` : null
      : tab === "funds" ? summary.linked.national_team_tracked ? `/national-team/series/${code}?${range}` : null
        : category ? `/sentiment/series/${category.category_key}?${range}` : null;
  const plot = useApiResource<Candle[] | ValuationData | NationalData | SentimentDaily[]>(path);
  const actual = useApiResource<ReviewMarkers>(tab === "price" && showActual && validDates ? `/account/review/${code}?${range}` : null);
  const candles = tab === "price" ? (plot.data as Candle[] | undefined) ?? [] : tab === "funds" ? (plot.data as NationalData | undefined)?.candles ?? [] : [];
  const valuation = tab === "valuation" ? plot.data as ValuationData | undefined : undefined;
  const national = tab === "funds" ? plot.data as NationalData | undefined : undefined;
  const sentiment = tab === "sentiment" ? plot.data as SentimentDaily[] | undefined : undefined;
  const latestMetric = summary?.summary.valuation?.metrics[metric];
  const change = summary?.summary.price.change_pct;
  const source = tab === "price" ? "财通证券日行情" : tab === "valuation" ? "韭圈估值／财通证券指数日行情" : tab === "funds" ? "韭圈固定基准估算／本地ETF日行情" : "韭圈行业恐贪与指数点位";
  const nationalUnsupported = tab === "funds" && summary && !summary.linked.national_team_tracked;
  const unavailable = tab === "valuation" && !index ? "尚无关联指数" : tab === "sentiment" && summary && !category ? "尚无市场情绪类别" : "";
  const hasPlot = tab === "price" ? candles.length > 0 : tab === "valuation" ? !!valuation?.series.length : tab === "funds" ? !!national?.holdings.length : !!sentiment?.length;

  return <section className="dossier-research" aria-label="ETF行情与背景">
    <Tabs label="图表维度" items={views} value={tab} onChange={(tab) => update({ tab })} toolbar={<div className="research-controls">
      {tab === "valuation" && <label>估值指标<select value={metric} onChange={(event) => update({ metric: event.target.value })}>{Object.entries(metrics).map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}</select></label>}
      {tab === "sentiment" && <label>市场类别<select aria-label="市场类别" value={category?.category_key ?? ""} onChange={(event) => update({ category: event.target.value })}>{summary?.summary.sentiment.map((item) => <option key={item.category_key} value={item.category_key}>{item.category_name}</option>)}</select></label>}
      <div className="research-date-range"><label>起始日期<input aria-label="起始日期" type="date" value={start} onChange={(event) => update({ start: event.target.value })} /></label><label>截止日期<input aria-label="截止日期" type="date" value={end} max={dateAgo(1)} onChange={(event) => update({ end: event.target.value })} /></label></div>
    </div>}>
    {query.legacy_index && <p className="notice">旧指数链接 {query.legacy_index} 已定位到关联 ETF，指数只提供因子。</p>}
    {error ? <div className="alert" role="alert">对象摘要暂不可用：{error}<button onClick={retry}>重试摘要</button></div> : loading ? <div className="empty skeleton-state" role="status">正在读取研究摘要…</div> : summary && <>
      <dl className="research-metrics">
        {tab === "price" ? <>
          <div><dt>最新收盘（元）</dt><dd>{number(summary.summary.price.value, 3)}</dd><small>{summary.summary.price.as_of ?? "暂无行情"}</small></div>
          <div><dt>日涨跌</dt><dd className={change == null || change === 0 ? "" : change > 0 ? "market-up" : "market-down"}>{change == null ? "—" : `${change > 0 ? "+" : ""}${number(change)}%`}</dd><small>最新数据 · 非实时</small></div>
          <div className="metric-context"><dt>图表区间</dt><dd className="range-value">{start} 至 {end}</dd><small>区间数据与最新摘要分开展示</small></div>
        </> : tab === "valuation" ? <>
          <div><dt>{metrics[metric].name}（{metrics[metric].unit}）</dt><dd>{number(latestMetric?.value)}</dd><small>{latestMetric?.trade_date ?? "暂无估值"}</small></div>
          <div><dt>本地十年回看分位</dt><dd>{latestMetric?.local_percentile == null ? "—" : `${number(latestMetric.local_percentile)}%`}</dd><small>截至各日的十日历年有效样本</small></div>
          <div><dt>来源当前分位</dt><dd>{latestMetric?.source_percentile == null ? "—" : `${number(latestMetric.source_percentile)}%`}</dd><small>非历史时点分位</small></div>
        </> : tab === "funds" ? <>
          <div><dt>国家队估算比例</dt><dd>{!summary.linked.national_team_tracked ? "未纳入跟踪" : summary.summary.national_team.ratio == null ? "—" : `${number(summary.summary.national_team.ratio)}%`}</dd><small>{summary.summary.national_team.as_of ?? "暂无比例"}</small></div>
          <div className="metric-context"><dt>估算口径</dt><dd>固定基准</dd><small>{national?.estimation_start_date ?? "2026-01-01"} · 不是真实持仓</small></div>
        </> : <>
          <div><dt>{category?.category_name ?? "市场类别"}恐贪分数</dt><dd className={category?.source_label?.includes("恐惧") ? "sentiment-fear-text" : category?.source_label?.includes("贪婪") ? "sentiment-greed-text" : ""}>{number(category?.fear_greed_score, 1)}</dd><small>{category?.source_label ?? "源标签暂无"} · {category?.last_date ?? "暂无数据"}</small></div>
          <div className="metric-context"><dt>适用范围</dt><dd>市场背景</dd><small>不是这只 ETF 的直接情绪或买卖信号</small></div>
        </>}
      </dl>
      {tab === "valuation" && <p className="context-note">关联指数：{summary.summary.valuation?.index_name ?? index ?? "未映射"} <span className="mono">{index}</span>；同指数 ETF 共享估值证据，历史源可能修订，未证明原时点可得。</p>}
      <div className="dossier-chart">
        {!validDates ? <div className="empty" role="alert">请选择有效的起止日期，起始日期不能晚于截止日期。</div> : nationalUnsupported ? <div className="empty"><h2>该 ETF 不在国家队数据源范围内</h2><p>数据源仅提供18只ETF，不包含 {code}；重新采集不会产生该标的数据。可在顶部切换至源支持的 ETF，如 510500 或 512100。</p></div> : unavailable ? <div className="empty"><p>{unavailable}</p><a href={dataManagementUrl("jobs", tasks[tab], code)}>检查对应数据任务</a></div>
          : plot.loading ? <div className="chart-loading skeleton-state" role="status">正在读取所选区间…</div> : plot.error ? <div className="empty" role="alert"><p>所选区间读取失败：{plot.error}</p><button onClick={plot.retry}>重试图表</button><a href={dataManagementUrl("jobs", tasks[tab], code)}>检查对应数据任务</a></div>
            : !hasPlot ? <div className="empty"><h2>所选区间暂无数据</h2><p>可以调整日期，或检查对应采集任务。</p><a href={dataManagementUrl("jobs", tasks[tab], code)}>检查对应数据任务</a></div> : <>
              {tab === "price" && <div className="chart-local-controls"><span className="muted">日 K · MA5 / 10 / 20 / 30 / 60</span><label><input type="checkbox" checked={showActual} onChange={(event) => setShowActual(event.target.checked)} />叠加真实操作</label></div>}
              {actual.error && <p className="notice warning">真实操作标记暂不可用，行情仍可查看。<button onClick={actual.retry}>重试标记</button></p>}
              {tab === "price" ? <KLine rows={candles} theme={theme} trades={showActual ? actual.data?.markers : []} />
                : tab === "valuation" ? <ValuationChart rows={valuation!.series} candles={valuation!.candles} title={metrics[metric].name} unit={metrics[metric].unit} theme={theme} />
                  : tab === "funds" ? <><KLine rows={candles} holdings={national!.holdings} theme={theme} />{!candles.length && <p className="notice warning">区间缺少本地日 K，仅展示估算比例，不伪造 ETF 价格。</p>}</>
                    : <SentimentTrend rows={sentiment!} theme={theme} />}
            </>}
      </div>
      <ChartCaption title={`${summary.object.name} · ${code} · 日频`} meta={`${start} 至 ${end} · ${source}${tab === "price" || tab === "funds" ? " · 复权口径未确认" : ""}`} />
      <details className="research-evidence"><summary>数据来源与使用边界</summary>
        {summary.warnings.map(message => <p key={message}>{message}</p>)}
        <p>最新摘要按各自源日期展示，不代表所选历史时点已知；图表仅展示所选日期区间。数据截止日期保留在各指标旁。</p>
        <p>行情来源：财通证券，原始日 K 复权口径未确认；个人记录为本地只读同步，未确认成交所属日前的标记仅用于核对。国家队为固定基准估算比例，零份额下为空；恐贪保留源类别和标签，不推断分类阈值。</p>
        <p>估值来源：韭圈；本地分位以截至各日十日历年有效样本统计，显示区间不改变回看窗口。修订历史不冒充原时点可得数据。</p>
        <a href={journeyUrl("etfs", code, { auxiliary: "compare", dimension: tab === "funds" ? "holdings" : tab === "price" ? "trend" : tab, start, end })}>进入跨 ETF 对比</a>
      </details>
    </>}
    </Tabs>
  </section>;
}
