import { test as base, expect, type Page, type Route } from "@playwright/test";

// 所有数值均为隔离的测试数据；拦截全部API，测试不会访问或修改真实账户。
export const instruments = ["510500", "512100"].map((code, index) => ({
  code, name: index ? "测试中证1000ETF" : "测试中证500ETF", enabled: true,
  start_date: "2024-01-01", first_date: "2024-01-02", last_date: "2026-11-06",
  count: 600, source: "测试行情",
}));
export const factorCatalog = {
  factors: [
    { id: "turning_bottom", name: "阶段底部确认", category: "结构确认" },
    { id: "turning_top", name: "阶段顶部确认", category: "结构确认" },
    { id: "volume_breakout_up", name: "放量向上突破", category: "突破确认" },
    { id: "close_above_prior_high", name: "收盘收复昨高", category: "反转确认" },
    { id: "erp_high_percentile", name: "股债高性价比保护", category: "外部估值" },
    { id: "relative_strength_20d_positive", name: "相对沪深300跑赢", category: "相对强弱" },
    { id: "oversold_recovery", name: "超跌后止跌修复", category: "反转确认" },
  ].map((factor) => ({ ...factor, meaning: "仅用于观察。", chart_visible: true, output_type: "event" })),
};
export const catalog = {
  instruments: instruments.map((item) => ({ instrument_code: item.code, instrument_name: item.name,
    first_date: item.first_date, last_date: item.last_date, default_start: "2025-01-02", default_end: item.last_date, source_checked_through: "2026-11-06" })),
  strategies: [["range_breakout", "箱体突破"], ["bottom_confirmation", "底部确认"], ["hybrid_reversal", "复合反转"]].map(([id, name]) => ({
    id, name, description: `${name}的测试规则`, supported_instruments: ["510500", "512100"],
    factors: [{ ...factorCatalog.factors[id === "range_breakout" ? 2 : 0], role: "trigger" }],
  })),
  assignments: [] as StrategyAssignment[],
};
export const settings = { instrument_code: "510500", start_date: "2025-01-02", end_date: "2026-11-06",
  initial_cash: "50000", commission_rate: "0.0001", minimum_commission: "0", slippage_bps: "5" };
type StrategyAssignment = { id: number; strategy_id: string; instrument_code: string; comparison_id: number; active: boolean; adopted_at: string };
export const assignment: StrategyAssignment = { id: 10, strategy_id: "range_breakout", instrument_code: "510500",
  comparison_id: 5, active: true, adopted_at: "2026-11-05T08:00:00Z" };
export const holdings = { as_of: "2026-11-06", items: instruments.map((item) => ({
  instrument_code: item.code, instrument_name: item.name, current_amount: 1000, enable_amount: 1000,
  market_value: 5000, cost_price: 4, latest_close_date: "2026-11-06",
})), summary: { holding_count: 2, configured_only: true } };
export const job = { enabled: true, time: "08:30", next_run: "2026-11-09T00:30:00Z", source_configured: true, runs: [] };
export const marketSentimentOverview = {
  latest: { trade_date: "2026-11-06", fear_greed_score: 20, source_label: "恐惧", changes: { one_day: -2, one_week: -5, one_month: -10 } },
  coverage: { first_source_date: "2020-08-03", last_source_date: "2026-11-06", count: 1533 },
  regime_factors: {
    volatility: { factor_name: "指数波动：50ETF期权波动率", raw_value: 23, trade_date: "2026-11-06", first_source_date: "2025-11-28", last_source_date: "2026-11-06", count: 242, source_pct_year: 80, source_pct_all: 90 },
    bx: { factor_name: "避险天堂：股债回报差", raw_value: -1.2, trade_date: "2026-11-06", first_source_date: "2025-11-28", last_source_date: "2026-11-06", count: 242, source_pct_year: 20, source_pct_all: 30 },
    premium: { factor_name: "升贴水率：沪深300股指期货升贴水", raw_value: -11, trade_date: "2026-11-06", first_source_date: "2025-11-28", last_source_date: "2026-11-06", count: 242, source_pct_year: 10, source_pct_all: 20 },
    wz: { factor_name: "两市成交额", raw_value: 1200000, trade_date: "2026-11-06", first_source_date: "2025-11-28", last_source_date: "2026-11-06", count: 242, source_pct_year: 60, source_pct_all: 50 },
    strength: { factor_name: "股价强度：创新高个股数量占比", raw_value: 0.8, trade_date: "2026-11-06", first_source_date: "2025-11-28", last_source_date: "2026-11-06", count: 242, source_pct_year: 15, source_pct_all: 20 },
  }, source: "韭圈 · fear-greed",
};
export const marketSentimentSeries = {
  fear_greed: [{ trade_date: "2026-11-05", fear_greed_score: 22, source_label: null, collected_at: "2026-11-06T00:00:00Z" }, { trade_date: "2026-11-06", fear_greed_score: 20, source_label: "恐惧", collected_at: "2026-11-06T00:00:00Z" }],
  regime_factors: Object.fromEntries(Object.entries(marketSentimentOverview.regime_factors).map(([key, item]) => [key, [{ trade_date: "2026-11-05", factor_name: item.factor_name, raw_value: item.raw_value, source_pct_year: item.source_pct_year, source_pct_all: item.source_pct_all, collected_at: "2026-11-06T00:00:00Z" }]])),
};
export const candles = Array.from({ length: 80 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 7, 1 + index)).toISOString().slice(0, 10);
  return { date, open: 5, high: 5.3, low: 4.8, close: 5 + index / 100, volume: 100000,
    amount: 500000, change_pct: index === 0 ? 0 : 0.2, source_updated_at: null, collected_at: "2026-11-06T00:00:00Z" };
});
export const comparison = {
  id: 5, instrument_code: "510500", created_at: "2026-11-06T08:00:00Z", settings,
  input_sha256: "test-input-snapshot", complete: true, data_cutoff: "2026-11-06",
  note: "测试模板回测结果，不代表未来表现。",
  market_rows: candles.map(({ date, ...rest }) => ({ ...rest, trade_date: date })),
  tracks: [{ key: "strategy:range_breakout", backtest_id: 1, name: "箱体突破", strategy_id: "range_breakout", status: "success", account: {
    daily: candles.map((row, index) => ({ trade_date: row.date, nav: 1 + index / 1000, drawdown: 0,
      cash: "0", quantity: 10000, equity: "51000", position_weight: 1, reason: "测试", execution_note: "", dividend_receivable: "0" })),
    trades: [], metrics: { total_return: 0.05, max_drawdown: -0.03, final_equity: "52500", trade_count: 2,
      commission: "5", slippage_cost: "10", turnover: 1, annual_return: 0.03, annual_volatility: 0.1 },
  }, diagnostics: { time_in_market: 0.8, completed_rounds: 1, open_rounds: 0,
    rounds: [{ entry_date: "2025-02-03", exit_date: "2025-03-03", pnl: "250.00" }] } }],
};
export function summary(code = "510500") {
  return { object: { type: "etf", code, name: instruments.find((item) => item.code === code)?.name },
    linked: { index_code: "000905.SH", instruments: [], national_team_tracked: true },
    summary: { price: { value: 5.123, change_pct: 0, as_of: "2026-11-06" }, valuation: { index_code: "000905.SH", index_name: "测试指数", metrics: {} },
      holding: holdings.items.find((item) => item.instrument_code === code), holdings_as_of: "2026-11-06",
      investment_status: "holding", trade_count: 0, national_team: { ratio: 0, as_of: "2026-11-06" }, sentiment: [] }, eligibility: [], warnings: [] };
}

export async function json(route: Route, data: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
}

export async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.slice(4);
    if (path === "/instruments") return json(route, instruments);
    if (path === "/market-sentiment/overview") return json(route, marketSentimentOverview);
    if (path.startsWith("/market-sentiment/series")) return json(route, marketSentimentSeries);
    if (path === "/account/holdings") return json(route, holdings);
    if (path === "/account/sync/status") return json(route, { latest: null, runs: [] });
    if (path.startsWith("/account/review/")) return json(route, { actual: { status: "not_applicable", reasons: ["测试：尚无可核算的真实成交"] },
      markers: [], start: settings.start_date, end: settings.end_date, quality: { issues: [] }, comparability: "测试数据不代表真实收益" });
    if (path === "/strategies/catalog") return json(route, catalog);
    if (path === "/strategies/comparisons") return json(route, request.method() === "POST" ? comparison : []);
    if (/\/strategies\/comparisons\/\d+$/.test(path)) return json(route, comparison);
    if (/\/strategies\/comparisons\/\d+\/verify$/.test(path)) return json(route, { identical: true });
    if (path === "/strategy-lab/signals") return json(route, []);
    if (path.endsWith("/job") || path === "/job") return json(route, job);
    if (path === "/research/universe") return json(route, { items: instruments.map((item) => ({ ...item, held: true })), default_code: "510500" });
    if (path === "/research/object") return json(route, summary(url.searchParams.get("code") || "510500"));
    if (/^\/etf-flows\/\d{6}\/summary$/.test(path)) return json(route, {
      latest: { trade_date: "2026-11-06", unit_shares_100m: 3.4, aum_100m: 12.5, net_share_flow_7d_100m: 0.2, net_share_flow_30d_100m: -0.3, discount_premium_pct: 0.12, purchase_status: "开放申购", redeem_status: "开放赎回", collected_at: "2026-11-07T00:00:00Z" },
      coverage: { first_trade_date: "2026-11-06", last_trade_date: "2026-11-06", count: 1 },
    });
    if (/^\/etf-flows\/\d{6}\/series$/.test(path)) return json(route, { series: [{ trade_date: "2026-11-06", unit_shares_100m: 3.4, aum_100m: 12.5, net_share_flow_7d_100m: 0.2, net_share_flow_30d_100m: -0.3, discount_premium_pct: 0.12, purchase_status: "开放申购", redeem_status: "开放赎回", collected_at: "2026-11-07T00:00:00Z" }] });
    if (path === "/factors") return json(route, factorCatalog);
    if (path.endsWith("/factors")) return json(route, { events: [], data_cutoff: null, partial: false, warmup_insufficient: false });
    if (path.startsWith("/candles/")) return json(route, candles);
    if (path === "/backtests") return json(route, []);
    return json(route, { detail: `测试未配置接口：${request.method()} ${path}` }, 404);
  });
}

export const test = base.extend({ page: async ({ page }, use) => { await mockApi(page); await use(page); } });
export { expect };
