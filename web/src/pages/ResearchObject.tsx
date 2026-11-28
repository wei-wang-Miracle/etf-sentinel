import { useState } from "react";
import AppLink from "../components/AppLink";
import ChartCaption from "../components/ChartCaption";
import Tabs from "../components/Tabs";
import KLine from "../components/KLine";
import EtfFlowChart, { type EtfFlowPoint as ChartEtfFlowPoint } from "../components/EtfFlowChart";
import EtfFactorChart from "../components/EtfFactorChart";
import ValuationChart from "../components/ValuationChart";
import { type Candle, type EtfFlowPoint } from "../lib/api";
import type { ValuationPoint } from "./IndexValuations";
import {
  MarketSentimentTrend,
  SentimentTrend,
  type MarketSentimentOverview,
  type MarketSentimentSeries,
  type SentimentDaily,
} from "./Sentiment";
import { dateAgo, metrics, number, useResearchQuery } from "../lib/research";
import { useApiResource } from "../lib/useApiResource";
import { dataManagementUrl } from "../lib/navigation";
import { journeyUrl } from "../lib/strategyJourney";

type Metric = { value: number | null; local_percentile: number | null; source_percentile: number | null; trade_date: string | null; value_status: string };
type CatalogProfileSummary = {
  fund_full_name?: string | null;
  category_primary?: string | null;
  category_tag?: string | null;
  tracking_index_code?: string | null;
  tracking_index_name?: string | null;
  index_corr?: number | null;
  setup_date?: string | null;
  management_fee_pct?: number | null;
  custody_fee_pct?: number | null;
};
export type ResearchSummary = {
  object: { type: string; code: string; name: string };
  linked: { index_code: string | null; national_team_tracked: boolean };
  summary: {
    price: { value: number | null; as_of: string | null; change_pct: number | null };
    valuation: { index_code: string; index_name: string; metrics: Record<string, Metric> } | null;
    national_team: { ratio: number | null; as_of: string | null };
    sentiment: { category_key: string; category_name: string; index_name?: string | null; fear_greed_score: number | null; last_date: string | null; source_label: string | null }[];
    catalog_profile?: CatalogProfileSummary | null;
  };
  redirected_from?: { type: string; code: string } | null;
  warnings: string[];
};
type ValuationData = { series: ValuationPoint[]; candles: Candle[] };
type NationalData = { estimation_start_date: string; holdings: { trade_date: string; estimated_holding_pct: number | null }[]; candles: Candle[] };
type EtfFlowData = { series: EtfFlowPoint[] };
type EtfFlowSummary = {
  profile?: CatalogProfileSummary | null;
  latest: EtfFlowPoint | null;
  coverage: { first_trade_date: string | null; last_trade_date: string | null; count: number };
};
type ReviewMarkers = { markers: { trade_date: string; side: string; quantity: string; price: string }[] };
const views = [{ value: "price", label: "行情" }, { value: "valuation", label: "关联估值" }, { value: "funds", label: "资金与份额" }, { value: "sentiment", label: "市场情绪" }];
const tasks: Record<string, string> = { price: "etf", valuation: "index-valuations", funds: "etf-flows", sentiment: "sentiment" };
const quickRanges = [{ label: "3M", days: 90 }, { label: "6M", days: 180 }, { label: "1Y", days: 365 }, { label: "3Y", days: 1095 }];
const ACCOUNT_SYNC_START = "2025-01-20";

export default function ResearchObject({ theme, code, summary, loading, error, retry }: {
  theme: string; code: string; summary?: ResearchSummary; loading: boolean; error: string; retry: () => void;
}) {
  const [query, update] = useResearchQuery({ tab: "price", start: dateAgo(365), end: dateAgo(1), metric: "pe", category: "", legacy_index: "", sentiment_scope: "industry", fund_view: "flows" });
  const [showActual, setShowActual] = useState(false);
  const tab = views.some((item) => item.value === query.tab) ? query.tab : "price";
  const metric = metrics[query.metric] ? query.metric : "pe";
  const { start, end } = query;
  const validDates = !!start && !!end && start <= end;
  const index = summary?.linked.index_code;
  const category = summary?.summary.sentiment.find((item) => item.category_key === query.category) ?? summary?.summary.sentiment[0];
  const sentimentScope = query.sentiment_scope === "market" || (tab === "sentiment" && !category) ? "market" : "industry";
  const fundView = query.fund_view === "national" ? "national" : "flows";
  const range = `start=${start}&end=${end}`;
  const today = dateAgo(0);
  const yesterday = dateAgo(1);
  const markerStart = start < ACCOUNT_SYNC_START ? ACCOUNT_SYNC_START : start;
  const markerEnd = end >= today ? yesterday : end;
  const markerRangeValid = validDates && markerStart <= markerEnd;
  const markerClamped = start < ACCOUNT_SYNC_START || end >= today;
  const path = !summary || !validDates ? null : tab === "price" ? `/candles/${code}?start=1990-01-01&end=${end}`
    : tab === "valuation" ? index ? `/index-valuations/series/${index}?${range}&metric=${metric}` : null
      : tab === "funds" ? fundView === "national" ? summary.linked.national_team_tracked ? `/national-team/series/${code}?${range}` : null : `/etf-flows/${code}/series?${range}`
        : sentimentScope === "industry" && category ? `/sentiment/series/${category.category_key}?${range}` : null;
  const plot = useApiResource<Candle[] | ValuationData | NationalData | EtfFlowData | SentimentDaily[]>(path);
  const flowSummary = useApiResource<EtfFlowSummary>(tab === "funds" && fundView === "flows" ? `/etf-flows/${code}/summary` : null);
  const flowCandles = useApiResource<Candle[]>(tab === "funds" && fundView === "flows" && validDates ? `/candles/${code}?start=${start}&end=${end}` : null);
  const marketOverview = useApiResource<MarketSentimentOverview>(tab === "sentiment" && sentimentScope === "market" ? "/market-sentiment/overview" : null);
  const marketSeries = useApiResource<MarketSentimentSeries>(tab === "sentiment" && sentimentScope === "market" && validDates ? `/market-sentiment/series?${range}` : null);
  const actual = useApiResource<ReviewMarkers>(tab === "price" && showActual && markerRangeValid ? `/account/review/${code}?start=${markerStart}&end=${markerEnd}` : null);
  const history = tab === "price" ? (plot.data as Candle[] | undefined) ?? [] : [];
  const candles = tab === "price" ? history.filter(row => row.date >= start && row.date <= end) : tab === "funds" && fundView === "national" ? (plot.data as NationalData | undefined)?.candles ?? [] : [];
  const valuation = tab === "valuation" ? plot.data as ValuationData | undefined : undefined;
  const national = tab === "funds" && fundView === "national" ? plot.data as NationalData | undefined : undefined;
  const flows = tab === "funds" && fundView === "flows" ? plot.data as EtfFlowData | undefined : undefined;
  const sentiment = tab === "sentiment" && sentimentScope === "industry" ? plot.data as SentimentDaily[] | undefined : undefined;
  const latestMetric = summary?.summary.valuation?.metrics[metric];
  const change = summary?.summary.price.change_pct;
  const source = tab === "price" ? "财通证券日行情" : tab === "valuation" ? "韭圈估值／财通证券指数日行情" : tab === "funds" ? fundView === "flows" ? "FundDB ETF档案与规模份额截面" : "韭圈固定基准估算／本地ETF日行情" : sentimentScope === "market" ? "韭圈全市场恐贪与五维环境" : "韭圈行业恐贪与指数点位";
  const nationalUnsupported = tab === "funds" && fundView === "national" && summary && !summary.linked.national_team_tracked;
  const unavailable = tab === "valuation" && !index ? "尚无关联指数" : tab === "sentiment" && sentimentScope === "industry" && summary && !category ? "尚无行业恐贪类别，可切换至全市场温度与波指" : "";
  const hasPlot = tab === "price" ? candles.length > 0 : tab === "valuation" ? !!valuation?.series.length : tab === "funds" ? fundView === "flows" ? !!flows?.series.length : !!national?.holdings.length : sentimentScope === "market" ? !!marketSeries.data?.fear_greed.length : !!sentiment?.length;
  const chartResource = tab === "sentiment" && sentimentScope === "market" ? marketSeries : plot;
  const targetTask = tab === "sentiment" && sentimentScope === "market" ? "market-sentiment" : tab === "funds" && fundView === "national" ? "national-team" : tasks[tab];
  const catalogProfile = summary?.summary.catalog_profile ?? flowSummary.data?.profile ?? null;

  return <section className="dossier-research" aria-label="ETF行情与背景">
    <Tabs label="图表维度" items={views} value={tab} onChange={(tab) => update({ tab })} toolbar={<div className="research-controls">
      {tab === "valuation" && <label>估值指标<select value={metric} onChange={(event) => update({ metric: event.target.value })}>{Object.entries(metrics).map(([key, item]) => <option key={key} value={key}>{item.name}</option>)}</select></label>}
      {tab === "funds" && <div className="segmented" role="group" aria-label="资金数据视图"><button aria-pressed={fundView === "flows"} onClick={() => update({ fund_view: "flows" })}>份额流与折溢价</button><button aria-pressed={fundView === "national"} onClick={() => update({ fund_view: "national" })}>国家队估算</button></div>}
      {tab === "sentiment" && <><div className="segmented" role="group" aria-label="情绪范围"><button aria-pressed={sentimentScope === "industry"} onClick={() => update({ sentiment_scope: "industry" })}>行业恐贪</button><button aria-pressed={sentimentScope === "market"} onClick={() => update({ sentiment_scope: "market" })}>全市场温度与波指</button></div>{sentimentScope === "industry" && <label>市场类别<select aria-label="市场类别" value={category?.category_key ?? ""} onChange={(event) => update({ category: event.target.value })}>{summary?.summary.sentiment.map((item) => <option key={item.category_key} value={item.category_key}>{item.category_name}</option>)}</select></label>}</>}
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
        </> : tab === "funds" && fundView === "flows" ? <>
          <div><dt>最新基金规模</dt><dd>{number(flowSummary.data?.latest?.aum_100m, 2)} 亿元</dd><small>{flowSummary.data?.latest?.trade_date ?? "暂无截面"}</small></div>
          <div><dt>近30日份额变动</dt><dd>{number(flowSummary.data?.latest?.net_share_flow_30d_100m, 2)} 亿份</dd><small>正负按 FundDB 源值保留</small></div>
          <div className="metric-context"><dt>本地积累</dt><dd>{flowSummary.data?.coverage.count ?? 0} 个截面日</dd><small>{flowSummary.data?.coverage.first_trade_date ?? "尚未采集"} 至 {flowSummary.data?.coverage.last_trade_date ?? "—"}</small></div>
        </> : tab === "funds" ? <>
          <div><dt>国家队估算比例</dt><dd>{!summary.linked.national_team_tracked ? "未纳入跟踪" : summary.summary.national_team.ratio == null ? "—" : `${number(summary.summary.national_team.ratio)}%`}</dd><small>{summary.summary.national_team.as_of ?? "暂无比例"}</small></div>
          <div className="metric-context"><dt>估算口径</dt><dd>固定基准</dd><small>{national?.estimation_start_date ?? "2026-01-01"} · 不是真实持仓</small></div>
        </> : sentimentScope === "market" ? <>
          <div><dt>全市场恐贪分</dt><dd className={marketOverview.data?.latest.source_label?.includes("恐惧") ? "sentiment-fear-text" : marketOverview.data?.latest.source_label?.includes("贪婪") ? "sentiment-greed-text" : ""}>{number(marketOverview.data?.latest.fear_greed_score, 1)}</dd><small>{marketOverview.data?.latest.source_label ?? "源标签暂无"} · {marketOverview.data?.latest.trade_date ?? "暂无数据"}</small></div>
          <div><dt>50ETF期权波动率</dt><dd>{number(marketOverview.data?.regime_factors.volatility?.raw_value, 2)}</dd><small>股债差 {number(marketOverview.data?.regime_factors.bx?.raw_value, 2)}% · {marketOverview.data?.regime_factors.volatility?.trade_date ?? "暂无数据"}</small></div>
          <div><dt>期指年化升贴水</dt><dd>{number(marketOverview.data?.regime_factors.premium?.raw_value, 2)}%</dd><small>创新高 {number(marketOverview.data?.regime_factors.strength?.raw_value, 2)}% · 成交 {number(marketOverview.data?.regime_factors.wz?.raw_value, 0)}</small></div>
        </> : <>
          <div><dt>{category?.category_name ?? "市场类别"}恐贪分数</dt><dd className={category?.source_label?.includes("恐惧") ? "sentiment-fear-text" : category?.source_label?.includes("贪婪") ? "sentiment-greed-text" : ""}>{number(category?.fear_greed_score, 1)}</dd><small>{category?.source_label ?? "源标签暂无"} · {category?.last_date ?? "暂无数据"}</small></div>
          <div className="metric-context"><dt>适用范围</dt><dd>市场背景</dd><small>不是这只 ETF 的直接情绪或买卖信号</small></div>
        </>}
      </dl>
      {tab === "funds" && catalogProfile && <p className="context-note">基金档案：{catalogProfile.fund_full_name ?? summary.object.name}{catalogProfile.category_tag ? ` · ${catalogProfile.category_tag}` : ""}{catalogProfile.setup_date ? ` · 成立 ${catalogProfile.setup_date}` : ""}{catalogProfile.management_fee_pct == null ? "" : ` · 费率 ${catalogProfile.management_fee_pct}%+${catalogProfile.custody_fee_pct ?? "—"}%`}{catalogProfile.tracking_index_code ? ` · 源跟踪 ${catalogProfile.tracking_index_code}` : ""}{catalogProfile.index_corr == null ? "" : `（相关度 ${catalogProfile.index_corr.toFixed(3)}）`}</p>}
      {tab === "funds" && fundView === "flows" && (flowSummary.data?.coverage.count ?? 0) > 0 && (flowSummary.data?.coverage.count ?? 0) < 5 && <p className="notice warning">已收集 {flowSummary.data!.coverage.count} 个截面日（{flowSummary.data!.coverage.first_trade_date} 起），历史日度资金流随每日任务 7 持续累积，不回填未采集历史。</p>}
      {tab === "valuation" && <p className="context-note">关联指数：{summary.summary.valuation?.index_name ?? index ?? "未映射"} <span className="mono">{index}</span>；同指数 ETF 共享估值证据，历史源可能修订，未证明原时点可得。</p>}
      <div className="dossier-chart">
        {!validDates ? <div className="empty" role="alert">请选择有效的起止日期，起始日期不能晚于截止日期。</div> : nationalUnsupported ? <div className="empty"><h2>该 ETF 不在国家队数据源范围内</h2><p>数据源仅提供18只ETF，不包含 {code}；重新采集不会产生该标的数据。可在顶部切换至源支持的 ETF，如 510500 或 512100。</p></div> : unavailable ? <div className="empty"><p>{unavailable}</p><AppLink href={dataManagementUrl("jobs", targetTask, code)}>检查对应数据任务</AppLink></div>
          : chartResource.loading || (tab === "sentiment" && sentimentScope === "market" && marketOverview.loading) ? <div className="chart-loading skeleton-state" role="status">正在读取所选区间…</div> : chartResource.error || (tab === "sentiment" && sentimentScope === "market" && marketOverview.error) ? <div className="empty" role="alert"><p>所选区间读取失败：{chartResource.error || marketOverview.error}</p><button onClick={() => { chartResource.retry(); marketOverview.retry(); }}>重试图表</button><AppLink href={dataManagementUrl("jobs", targetTask, code)}>检查对应数据任务</AppLink></div>
            : !hasPlot ? <div className="empty"><h2>所选区间暂无数据</h2><p>可以调整日期，或检查对应采集任务。</p><AppLink href={dataManagementUrl("jobs", targetTask, code)}>检查对应数据任务</AppLink></div> : <>
              {showActual && !markerRangeValid && <p className="notice">所选区间早于账户同步起点（{ACCOUNT_SYNC_START}），暂无真实操作记录可叠加。</p>}
              {showActual && markerRangeValid && markerClamped && !actual.error && <p className="muted">真实操作仅叠加账户同步起点（{ACCOUNT_SYNC_START}）至昨日的已同步记录。</p>}
              {actual.error && <p className="notice warning">真实操作标记暂不可用（{actual.error}），行情仍可查看。<button onClick={actual.retry}>重试标记</button></p>}
              {tab === "price" ? <EtfFactorChart history={history} start={start} end={end} theme={theme} instrumentCode={code}
                trades={showActual ? actual.data?.markers : undefined}
                controls={<>
                  <select
                    className="quick-range-select"
                    aria-label="快捷日期区间"
                    value={quickRanges.find((item) => start === dateAgo(item.days) && end === dateAgo(1))?.label ?? ""}
                    onChange={(event) => {
                      const picked = quickRanges.find((item) => item.label === event.target.value);
                      if (picked) update({ start: dateAgo(picked.days), end: dateAgo(1) });
                    }}
                  >
                    <option value="">快捷区间</option>
                    {quickRanges.map((item) => <option key={item.label} value={item.label}>近 {item.label}</option>)}
                  </select>
                  <label><input type="checkbox" checked={showActual} onChange={event => setShowActual(event.target.checked)} />叠加真实操作</label>
                </>} />
                : tab === "valuation" ? <ValuationChart rows={valuation!.series} candles={valuation!.candles} title={metrics[metric].name} unit={metrics[metric].unit} theme={theme} />
              : tab === "funds" ? fundView === "flows" ? <EtfFlowChart rows={(flows!.series as ChartEtfFlowPoint[])} candles={flowCandles.data ?? []} theme={theme} /> : <><KLine rows={candles} holdings={national!.holdings} theme={theme} />{!candles.length && <p className="notice warning">区间缺少本地日 K，仅展示估算比例，不伪造 ETF 价格。</p>}</>
                    : sentimentScope === "market" ? <><MarketSentimentTrend rows={marketSeries.data!} theme={theme} /><p className="muted">子因子自 {marketOverview.data?.regime_factors.volatility?.first_source_date ?? "首次成功采集日"} 起本地累积，早于该日无数据不补零。</p></>
                      : <SentimentTrend rows={sentiment!} theme={theme} />}
            </>}
      </div>
      <ChartCaption title={`来源：${source}`} meta={tab === "price" ? "前复权 OHLC" : tab === "funds" ? fundView === "flows" ? "源缺日不补零；尚不参与策略因子" : "复权口径未确认" : sentimentScope === "market" ? "总分自2020-08起；五维子因子按日累积" : "日频"} />
      <details className="research-evidence"><summary>数据来源与使用边界</summary>
        {summary.warnings.map(message => <p key={message}>{message}</p>)}
        {tab === "price" ? (
          <p>行情取自财通证券历史日频数据，按源复权收盘比率前复权展示；个人成交标记仅作叠加核对。</p>
        ) : tab === "valuation" ? (
          <p>估值取自韭圈，本地分位按截至当日的十日历年有效样本统计，切换显示区间不改变统计窗口。</p>
        ) : tab === "funds" && fundView === "flows" ? (
          <p>份额流、规模和折溢价来自 FundDB，只保存配置内 ETF 的本地累积截面；不插值、不补零，当前不参与策略因子。</p>
        ) : tab === "funds" ? (
          <p>国家队比例为固定基准估算值，不代表真实持仓；零份额时显示为空。</p>
        ) : sentimentScope === "market" ? (
          <p>全市场温度和五维环境是共同背景，因子真值仅使用严格早于 ETF 交易日的最近源观测；来源全历史分位不参与策略判断。</p>
        ) : (
          <p>行业恐贪保留源类别与标签作为市场背景参考，不直接映射为单只 ETF 买卖信号。</p>
        )}
      </details>
    </>}
    </Tabs>
  </section>;
}
