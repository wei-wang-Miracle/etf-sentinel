import { useEffect, useState } from "react";
import ChartCaption from "../components/ChartCaption";
import KLine from "../components/KLine";
import ValuationChart from "../components/ValuationChart";
import { api, type Candle } from "../lib/api";
import type { ValuationPoint } from "./IndexValuations";
import { dateAgo, metrics, number, useResearchQuery } from "../lib/research";
import type { AccountHoldings } from "../lib/account";

type Metric = {
  value: number | null;
  local_percentile: number | null;
  source_percentile: number | null;
  trade_date: string | null;
  value_status: string;
};
type IndexItem = {
  index_code: string;
  index_name: string;
  metrics: Record<string, Metric>;
};
type Summary = {
  object: { type: string; code: string; name: string };
  linked: {
    index_code: string | null;
    instruments: {
      code: string;
      name: string;
      national_team_ratio: number | null;
      national_team_as_of: string | null;
    }[];
    national_team_tracked: boolean;
  };
  summary: {
    price: {
      value: number | null;
      as_of: string | null;
      change_pct: number | null;
    };
    valuation: IndexItem | null;
    holding: AccountHoldings["items"][number] | null;
    investment_status: string;
    holdings_as_of: string | null;
    trade_count: number;
    national_team: { ratio: number | null; as_of: string | null };
    sentiment: {
      category_key: string;
      category_name: string;
      fear_greed_score: number | null;
      last_date: string | null;
      source_label: string | null;
    }[];
  };
  eligibility: { code: string; status: string; reason: string }[];
  redirected_from?: { type: string; code: string } | null;
  warnings: string[];
};
type Plot = {
  actual?: {
    status: string;
    reasons?: string[];
    net_pnl?: string;
    xirr?: number | null;
  };
  experiments?: {
    id: number;
    instrument_code: string;
    created_at: string;
    strategy_key: string;
    strategy_name?: string;
  }[];
  candles?: Candle[];
  series?: ValuationPoint[];
  holdings?: { trade_date: string; estimated_holding_pct: number | null }[];
  markers?: {
    trade_date: string;
    side: string;
    quantity: string;
    price: string;
  }[];
};
const tabs: Record<string, string> = {
  overview: "概览",
  price: "行情与趋势",
  valuation: "估值",
  funds: "情绪与资金",
  investment: "我的投资",
  factors: "因子",
  strategy: "策略",
};
const investmentNames: Record<string, string> = {
  not_synced: "尚未同步",
  holding: "当前持仓",
  closed: "历史有成交，当前快照未持有",
  not_traded: "尚无实际成交",
};

export default function ResearchObject({ theme }: { theme: string }) {
  const [query, update] = useResearchQuery({
    object: "",
    legacy_index: "",
    tab: "overview",
    start: dateAgo(365),
    end: dateAgo(1),
    metric: "pe",
  });
  const [kind, code] = /^(etf:\d{6}|index:[\dA-Z.]+)$/.test(query.object)
    ? query.object.split(":")
    : ["etf", ""];
  const tab = tabs[query.tab] ? query.tab : "overview",
    metric = metrics[query.metric] ? query.metric : "pe";
  const { start, end } = query;
  const [universe, setUniverse] = useState<{ value: string; label: string }[]>(
    [],
  );
  const [data, setData] = useState<Summary | null>(null);
  const [plot, setPlot] = useState<Plot | null>(null);
  const [error, setError] = useState("");
  const [plotError, setPlotError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api<{ items: { code: string; name: string; held: boolean }[]; default_code: string | null }>(
      "/research/universe", "GET", undefined, controller.signal,
    ).then((result) => {
      setUniverse(result.items.map((item) => ({
        value: `etf:${item.code}`,
        label: `${item.code} · ${item.name}${item.held ? " · 当前持仓" : ""}`,
      })));
      if (!/^(etf:\d{6}|index:[\dA-Z.]+)$/.test(new URLSearchParams(location.search).get("object") ?? "")) {
        if (result.default_code) update({ object: `etf:${result.default_code}` });
        else { setLoading(false); setError("尚无配置内ETF，请先配置标的。"); }
      }
    }).catch((e) => {
      if (!controller.signal.aborted) { setError(e.message); setLoading(false); }
    });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    const controller = new AbortController();
    if (!code) return;
    setData(null);
    setError("");
    setLoading(true);
    api<Summary>(
      `/research/object?object_type=${kind}&code=${code}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((result) => {
        if (result.redirected_from) {
          update({ object: `etf:${result.object.code}`, legacy_index: result.redirected_from.code });
        } else setData(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [kind, code, refresh]);
  useEffect(() => {
    const controller = new AbortController();
    setPlot(null);
    setPlotError("");
    if (!data || data.object.code !== code || !start || !end || start > end) return;
    const load = <T,>(path: string) =>
      api<T>(path, "GET", undefined, controller.signal);
    const current = data;
    const index = current.linked.index_code;
    async function run() {
      if (tab === "price" || tab === "overview") {
        const rows = await load<Candle[]>(
          `/candles/${code}?start=${start}&end=${end}`,
        );
        let markers: Plot["markers"] = [];
        if (tab === "price") {
          try {
            markers = (
              await load<Plot>(
                `/account/review/${code}?start=${start}&end=${end}`,
              )
            ).markers;
          } catch {
            if (!controller.signal.aborted)
              setPlotError("成交标记暂不可用，行情仍可查看");
          }
        }
        return {
          candles: tab === "overview" ? rows.slice(-60) : rows,
          markers,
        };
      }
      if (tab === "investment")
        return await load<Plot>(
          `/account/review/${code}?start=${start}&end=${end}`,
        );
      if (tab === "strategy") {
        const experiments =
          await load<NonNullable<Plot["experiments"]>>(`/backtests?instrument_code=${code}`);
        return {
          experiments: experiments.filter((row) =>
            current.eligibility.some(
              (item) => item.code === row.instrument_code,
            ),
          ),
        };
      }
      if (tab === "valuation" && index)
        return await load<Plot>(
          `/index-valuations/series/${index}?start=${start}&end=${end}&metric=${metric}`,
        );
      if (
        tab === "funds" &&
        current.linked.national_team_tracked
      )
        return await load<Plot>(
          `/national-team/series/${code}?start=${start}&end=${end}`,
        );
      return {};
    }
    run()
      .then((result) => {
        if (!controller.signal.aborted) setPlot(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setPlotError(e.message);
      });
    return () => controller.abort();
  }, [data, kind, code, tab, metric, start, end, refresh]);
  const holding = data?.summary.holding,
    valuation = data?.summary.valuation;
  const validDates = start && end && start <= end;
  const indexLink = data?.linked.index_code;
  return (
    <>
      <header className="page-header">
        <div>
          <h1>研究对象</h1>
          <p>同一对象，逐项核对来源、日期与适用边界</p>
        </div>
        <a
          href={`?page=compare&dimension=${tab === "valuation" ? "valuation" : "trend"}&start=${start}&end=${end}`}
        >
          横向对比 →
        </a>
      </header>
      <section className="panel research-chart-panel integrated-research">
        <div className="panel-header">
          <label className="compact-selector">
            研究对象{" "}
            <select
              aria-label="研究对象"
              value={`${kind}:${code}`}
              onChange={(e) => update({ object: e.target.value, legacy_index: "" })}
            >
              {universe.map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>
          <div className="date-controls">
            <label>
              起始{" "}
              <input
                type="date"
                value={start}
                onChange={(e) => update({ start: e.target.value })}
              />
            </label>
            <label>
              截止{" "}
              <input
                type="date"
                value={end}
                onChange={(e) => update({ end: e.target.value })}
              />
            </label>
          </div>
        </div>
        {query.legacy_index && <p className="notice warning">旧指数链接 {query.legacy_index} 已转到关联ETF；指数只作为因子来源，关联ETF可在上方切换。</p>}
        {(query.object && query.object !== `${kind}:${code}`) || tab !== query.tab ? (
          <p role="alert">无效对象或分区已回退为默认值。</p>
        ) : null}
        {loading ? (
          <div className="empty" role="status">
            正在汇总本地数据…
          </div>
        ) : error ? (
          <div className="empty" role="alert">
            {error}{" "}
            <button onClick={() => setRefresh(refresh + 1)}>重试</button>
          </div>
        ) : (
          data && (
            <>
              <div className="quote-strip">
                <div>
                  <span>ETF</span>
                  <strong>{data.object.name}</strong>
                  <small>
                    {code} ·{" "}
                    {indexLink ? (
                      <a
                        href={`?page=research&object=etf:${code}&tab=valuation&start=${start}&end=${end}`}
                      >
                        关联指数 {indexLink}
                      </a>
                    ) : (
                      "无关联指数"
                    )}
                  </small>
                </div>
                <div>
                  <span>
                    最新收盘（元） / 日变化
                  </span>
                  <strong>
                    {number(data.summary.price.value, 3)} /{" "}
                    {number(data.summary.price.change_pct)}%
                  </strong>
                  <small>{data.summary.price.as_of ?? "暂无行情"}</small>
                </div>
                <div>
                  <span>市盈率 / 本地分位</span>
                  <strong>
                    {number(valuation?.metrics.pe?.value)} /{" "}
                    {number(valuation?.metrics.pe?.local_percentile)}%
                  </strong>
                  <small>
                    {valuation?.metrics.pe?.trade_date ?? "暂无数据"}
                  </small>
                </div>
                <div>
                  <span>国家队估算比例</span>
                  <strong>
                    {data.linked.national_team_tracked
                      ? `${number(data.summary.national_team.ratio)}%`
                      : "未纳入跟踪"}
                  </strong>
                  <small>{data.summary.national_team.as_of}</small>
                </div>
                <div>
                  <span>我的投资 · 当前快照</span>
                  <strong>
                    {investmentNames[data.summary.investment_status]}
                  </strong>
                  <small>
                    {data.summary.holdings_as_of ?? "不适用／未同步"}
                  </small>
                </div>
              </div>
              <div
                className="research-tabs"
                role="tablist"
                aria-label="研究分区"
              >
                {Object.entries(tabs).map(([key, name], i, all) => (
                  <button
                    key={key}
                    id={`tab-${key}`}
                    role="tab"
                    aria-selected={tab === key}
                    aria-controls={`panel-${key}`}
                    tabIndex={tab === key ? 0 : -1}
                    onKeyDown={(e) => {
                      if (
                        ["ArrowRight", "ArrowLeft", "Home", "End"].includes(
                          e.key,
                        )
                      ) {
                        e.preventDefault();
                        const next =
                          e.key === "Home"
                            ? 0
                            : e.key === "End"
                              ? all.length - 1
                              : (i +
                                  (e.key === "ArrowRight" ? 1 : -1) +
                                  all.length) %
                                all.length;
                        update({ tab: all[next][0] });
                        document.getElementById(`tab-${all[next][0]}`)?.focus();
                      }
                    }}
                    onClick={() => update({ tab: key })}
                  >
                    {name}
                  </button>
                ))}
              </div>
              <div
                role="tabpanel"
                id={`panel-${tab}`}
                aria-labelledby={`tab-${tab}`}
              >
                {!validDates ? (
                  <div className="empty">请选择有效的起止日期</div>
                ) : (
                  <>
                    {plotError && (
                      <div className="notice warning" role="alert">
                        {plotError}{" "}
                        <button onClick={() => setRefresh(refresh + 1)}>
                          重试
                        </button>
                      </div>
                    )}
                    {(tab === "price" || tab === "overview") &&
                      (plot === null && !plotError ? (
                        <div className="empty" role="status">
                          正在读取行情…
                        </div>
                      ) : plot?.candles?.length ? (
                        <>
                          <div className="chart-toolbar">
                            <span>
                              最新收盘 {number(plot.candles.at(-1)?.close, 3)} ·{" "}
                              {plot.candles.at(-1)?.date}
                            </span>
                            <span>
                              区间价格变化{" "}
                              {number(
                                (plot.candles.at(-1)!.close /
                                  plot.candles[0].close -
                                  1) *
                                  100,
                              )}
                              %
                            </span>
                          </div>
                          <KLine
                            rows={plot.candles}
                            theme={theme}
                            trades={plot.markers}
                          />
                        </>
                      ) : (
                        <div className="empty">
                          区间暂无行情，请检查采集任务
                        </div>
                      ))}
                    {(tab === "valuation" || tab === "overview") && (
                      <>
                        <h2>关联指数估值</h2>
                        <p className="muted">来源：{valuation?.index_name ?? indexLink ?? "尚无关联指数"}；跟踪同一指数的ETF共享估值信息，不是独立证据。</p>
                        <div className="quote-strip">
                          {Object.entries(metrics).map(([key, value]) => {
                            const m = valuation?.metrics[key];
                            return (
                              <div key={key}>
                                <span>
                                  {value.name} · {value.unit}
                                </span>
                                <strong>{number(m?.value)}</strong>
                                <small>
                                  本地分位 {number(m?.local_percentile)}% ·{" "}
                                  {m?.trade_date ?? "暂无"}
                                </small>
                                <small>
                                  来源当前分位 {number(m?.source_percentile)}
                                  %（非历史时点）
                                </small>
                              </div>
                            );
                          })}
                        </div>
                        {tab === "valuation" && (
                          <>
                            <label>
                              指标{" "}
                              <select
                                value={metric}
                                onChange={(e) =>
                                  update({ metric: e.target.value })
                                }
                              >
                                {Object.entries(metrics).map(([key, value]) => (
                                  <option key={key} value={key}>
                                    {value.name}
                                  </option>
                                ))}
                              </select>
                            </label>
                            {!indexLink ? (
                              <div className="empty">无关联指数</div>
                            ) : plot?.series?.length ? (
                              <ValuationChart
                                rows={plot.series}
                                candles={plot.candles ?? []}
                                title={metrics[metric].name}
                                unit={metrics[metric].unit}
                                theme={theme}
                              />
                            ) : (
                              <div className="empty">
                                {plot === null
                                  ? "正在读取估值…"
                                  : "所选区间无估值数据"}
                              </div>
                            )}
                          </>
                        )}
                      </>
                    )}
                    {(tab === "funds" || tab === "overview") && (
                      <>
                        <h2>市场情绪背景</h2>
                        <p className="muted">
                          不是本对象的直接情绪；不从分数推断买卖信号。
                        </p>
                        <div className="quote-strip">
                          {data.summary.sentiment.map((row) => (
                            <div key={row.category_key}>
                              <span>{row.category_name}</span>
                              <strong>{number(row.fear_greed_score, 1)}</strong>
                              <small>
                                {row.source_label ?? "源标签暂无"} ·{" "}
                                {row.last_date ?? "无数据"}
                              </small>
                              <a
                                href={`?page=compare&dimension=sentiment&codes=${encodeURIComponent(row.category_key)}&start=${start}&end=${end}`}
                              >
                                比较走势
                              </a>
                            </div>
                          ))}
                        </div>
                        {tab === "funds" && (
                          <>
                            <h2>国家队估算持仓</h2>
                            {!data.linked.national_team_tracked ? (
                              <div className="empty">
                                未纳入国家队源目录，不补零
                              </div>
                            ) : plot?.holdings?.length ? (
                              <KLine
                                rows={plot.candles ?? []}
                                holdings={plot.holdings}
                                theme={theme}
                              />
                            ) : (
                              <div className="empty">
                                {plot === null
                                  ? "正在读取比例…"
                                  : "所选区间暂无估算比例"}
                              </div>
                            )}
                          </>
                        )}
                      </>
                    )}
                    {tab === "investment" && (
                      <>
                        <h2>个人账户参考</h2>
                        {plot?.actual && (
                          <p>
                            区间核算：
                            {plot.actual.status === "available"
                              ? `净盈亏 ${number(plot.actual.net_pnl)} 元`
                              : (plot.actual.reasons?.join("；") ?? "待核验")}
                          </p>
                        )}
                        <p>
                          {investmentNames[data.summary.investment_status]} ·
                          有效成交委托 {data.summary.trade_count} 条
                        </p>
                        {holding && (
                          <div className="quote-strip">
                            <div>
                              <span>当前数量（份）</span>
                              <strong>
                                {number(holding.current_amount, 0)}
                              </strong>
                            </div>
                            <div>
                              <span>源成本参考（元）</span>
                              <strong>{number(holding.cost_price, 3)}</strong>
                            </div>
                            <div>
                              <span>本地市值（元）</span>
                              <strong>{number(holding.market_value)}</strong>
                              <small>{holding.latest_close_date}</small>
                            </div>
                          </div>
                        )}
                        <p className="muted">
                          当前快照不是历史仓位，源成本参考不等同完整流水净盈亏。复盘页核验后查看真实金额曲线与研究基线。
                        </p>
                        {[{ code, name: data.object.name }].map((i) => (
                          <p key={i.code}>
                            <a
                              href={`?page=review&code=${i.code}&start=${start}&end=${end}`}
                            >
                              {i.name} · 查看完整复盘 →
                            </a>
                          </p>
                        ))}
                      </>
                    )}
                    {tab === "factors" && (
                      <div className="empty">
                        基础趋势、动量与波动已接入持仓策略研究；其他因子尚未用于交易规则，不构造七因子等权总分或上涨概率。已有估值分位可在估值分区查看。
                      </div>
                    )}
                    {tab === "strategy" && (
                      <>
                        <h2>规则研究</h2>
                        <p><a href="?page=backtests">当前持仓候选研究与观察计划 →</a></p>
                        {plot?.experiments?.map((run) => (
                          <p key={run.id}>
                            <a href={`?page=backtests&run_id=${run.id}`}>
                              已保存实验 #{run.id} · {run.instrument_code} ·
                              {run.strategy_name ?? "已保存规则"} · {run.created_at.slice(0, 10)}
                            </a>
                          </p>
                        ))}
                        <p className="muted">
                          研究账户每只ETF满仓资金为50,000元，与真实同步持仓分开。本页不自动运行实验，均线规则不代表你的实际交易策略。
                        </p>
                        {data.eligibility.map((row) => (
                          <p key={row.code}>
                            {row.code} ·{" "}
                            {row.status === "available"
                              ? "已有行情与权益源"
                              : "待核验"}{" "}
                            · {row.reason}{" "}
                            <a
                              href={`?page=review&code=${row.code}&start=${start}&end=${end}`}
                            >
                              持有 / 均线 / 现金研究 →
                            </a>
                          </p>
                        ))}
                      </>
                    )}
                  </>
                )}
              </div>
              <ChartCaption
                title={`${data.object.name} · ${code} · 日频`}
                meta={`${start} 至 ${end} · ETF原始价格，复权口径未确认 · 财通证券行情／韭圈指标 · 查看时间 ${new Date().toLocaleString("zh-CN")}`}
              />
              <p className="muted">
                原始日K，复权口径未确认；实际标记按委托日展示，成交所属日未确认前仅供核对
                。估值来源：韭圈；行情：财通证券；比例：韭圈固定基准估算；个人记录：本地同步。各区块日期独立，最新摘要不表示所选历史时点已知。仅供研究。
              </p>
            </>
          )
        )}
      </section>
    </>
  );
}
