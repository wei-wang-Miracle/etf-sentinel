import { test as base, expect, type Page, type Route } from "@playwright/test";

// 所有数值均为隔离的测试数据；拦截全部API，测试不会访问或修改真实账户。
export const instruments = ["510500", "512100"].map((code, index) => ({
  code, name: index ? "测试中证1000ETF" : "测试中证500ETF", enabled: true,
  start_date: "2024-01-01", first_date: "2024-01-02", last_date: "2026-11-06",
  count: 600, source: "测试行情",
}));
export const catalog = {
  instruments: instruments.map((item) => ({ instrument_code: item.code, instrument_name: item.name,
    first_date: item.first_date, last_date: item.last_date, default_start: "2025-01-02", source_checked_through: "2026-11-06" })),
  conditions: [
    { key: "trend", label: "含分红走势相对均线", unit: "%", window: true, description: "含分红走势相对均线的偏离", evidence_type: "historical" },
    { key: "momentum", label: "含分红走势动量", unit: "%", window: true, description: "回看区间变化", evidence_type: "historical" },
    { key: "pe_percentile", label: "市盈率本地分位", unit: "%", window: false, description: "本地十年分位", evidence_type: "revised" },
  ],
  sentiment_categories: [{ key: "wide", name: "测试宽基" }],
};
export const rule = {
  buy: { mode: "all", conditions: [{ indicator: "trend", window: 60, operator: "gt", threshold: "0" }] },
  sell: { mode: "any", conditions: [{ indicator: "trend", window: 60, operator: "lte", threshold: "0" }] }, allocation: 100,
};
export const settings = { instrument_code: "510500", start_date: "2025-01-02", end_date: "2026-11-06",
  initial_cash: "50000", commission_rate: "0.0001", minimum_commission: "0", slippage_bps: "5" };
export const savedVersion = { id: 10, strategy_id: 1, name: "测试趋势", version: 1, instrument_code: "510500",
  rule, settings, backtest_id: 1, active: false, observation_id: 11, created_at: "2026-11-06T08:00:00Z" };
export const holdings = { as_of: "2026-11-06", items: instruments.map((item) => ({
  instrument_code: item.code, instrument_name: item.name, current_amount: 1000, enable_amount: 1000,
  market_value: 5000, cost_price: 4, latest_close_date: "2026-11-06",
})), summary: { holding_count: 2, configured_only: true } };
export const job = { enabled: true, time: "08:30", next_run: "2026-11-09T00:30:00Z", source_configured: true, runs: [] };
export const candles = Array.from({ length: 80 }, (_, index) => {
  const date = new Date(Date.UTC(2026, 7, 1 + index)).toISOString().slice(0, 10);
  return { date, open: 5, high: 5.3, low: 4.8, close: 5 + index / 100, volume: 100000,
    amount: 500000, change_pct: index === 0 ? 0 : 0.2, source_updated_at: null, collected_at: "2026-11-06T00:00:00Z" };
});
export const comparison = {
  id: 5, instrument_code: "510500", created_at: "2026-11-06T08:00:00Z", settings,
  input_sha256: "test-input-snapshot", complete: true,
  market_rows: candles.map(({ date, ...rest }) => ({ ...rest, trade_date: date })),
  tracks: [{ key: "current", name: "当前草稿", status: "success", evidence_type: "historical", account: {
    daily: candles.map((row, index) => ({ trade_date: row.date, nav: 1 + index / 1000, drawdown: 0,
      cash: "0", quantity: 10000, equity: "51000", position_weight: 1, reason: "测试", execution_note: "", dividend_receivable: "0" })),
    trades: [], metrics: { total_return: 0.05, max_drawdown: -0.03, final_equity: "52500", trade_count: 2,
      commission: "5", slippage_cost: "10", turnover: 1, annual_return: 0.03, annual_volatility: 0.1 },
  }, diagnostics: { time_in_market: 0.8, completed_rounds: 1, open_rounds: 0 } }],
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
    if (path === "/account/holdings") return json(route, holdings);
    if (path === "/account/sync/status") return json(route, { latest: null, runs: [] });
    if (path.startsWith("/account/review/")) return json(route, { actual: { status: "not_applicable", reasons: ["测试：尚无可核算的真实成交"] },
      markers: [], start: settings.start_date, end: settings.end_date, quality: { issues: [] }, comparability: "测试数据不代表真实收益" });
    if (path === "/strategies/catalog") return json(route, catalog);
    if (path === "/strategies/coverage") return json(route, { conditions: catalog.conditions.map((item) => ({ key: item.key,
      status: item.evidence_type, first_date: "2024-01-02", last_date: "2026-11-06" })) });
    if (path.startsWith("/strategies/drafts/")) return json(route, null);
    if (path === "/strategies/comparisons") return json(route, request.method() === "POST" ? comparison : []);
    if (path === "/strategies") return json(route, request.method() === "POST" ? savedVersion : []);
    if (/\/strategies\/\d+\/enable/.test(path)) return json(route, { ...savedVersion, active: true });
    if (path === "/strategy-lab/signals" || path === "/strategy-lab/observations") return json(route, []);
    if (path.endsWith("/job") || path === "/job") return json(route, job);
    if (path === "/research/universe") return json(route, { items: instruments.map((item) => ({ ...item, held: true })), default_code: "510500" });
    if (path === "/research/object") return json(route, summary(url.searchParams.get("code") || "510500"));
    if (path.startsWith("/candles/")) return json(route, candles);
    if (path === "/backtests") return json(route, []);
    return json(route, { detail: `测试未配置接口：${request.method()} ${path}` }, 404);
  });
}

export const test = base.extend({ page: async ({ page }, use) => { await mockApi(page); await use(page); } });
export { expect };
