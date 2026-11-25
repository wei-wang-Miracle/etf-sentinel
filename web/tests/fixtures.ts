import { test as base, expect, type Page, type Route } from "@playwright/test";

// 所有数值均为隔离的测试数据；拦截全部API，测试不会访问或修改真实账户。
export const instruments = ["510500", "512100"].map((code, index) => ({
  code, name: index ? "测试中证1000ETF" : "测试中证500ETF", enabled: true,
  start_date: "2024-01-01", first_date: "2024-01-02", last_date: "2026-11-06",
  count: 600, source: "测试行情",
}));
export const catalog = {
  instruments: instruments.map((item) => ({ instrument_code: item.code, instrument_name: item.name,
    first_date: item.first_date, last_date: item.last_date, default_start: "2025-01-02", default_end: item.last_date, source_checked_through: "2026-11-06" })),
  templates: [["range_breakout", "箱体突破"], ["bottom_confirmation", "底部确认"]].map(([id, name]) => ({
    id, version: "1.0.0", name, status: "experimental", description: `${name}的测试规则`,
    supported_instruments: ["510500", "512100"], note: "回测不代表未来收益。",
    turning_profiles_by_instrument: {
      "510500": { group: "mid", group_name: "中盘", parameters: { background_days: 3, slope_threshold: 0.01, breakout_window: 3, confirmation_ma_window: 20, confirmation_days: 3, breakout_atr_multiplier: 0.2, cooldown_days: 30, top_breakout_window: 3, top_ma_window: 3, top_confirmation_days: 1, top_trailing_atr: 3 } },
      "512100": { group: "small", group_name: "小盘", parameters: { background_days: 5, slope_threshold: 0.01, breakout_window: 3, confirmation_ma_window: 5, confirmation_days: 3, breakout_atr_multiplier: 0.2, cooldown_days: 0, top_breakout_window: 3, top_ma_window: 3, top_confirmation_days: 1, top_trailing_atr: 3 } },
    },
  })),
};
export const template = {
  id: "range_breakout", version: "1.0.0", name: "箱体突破", status: "experimental",
  rule: { family: "breakout", fast: 5, slow: 60, buy_votes: 3, value_max: 80 },
  algorithm_version: "multifactor-v1", turning_version: "slope-structure-paired-v4",
  note: "回测不代表未来收益。",
};
export const settings = { instrument_code: "510500", start_date: "2025-01-02", end_date: "2026-11-06",
  initial_cash: "50000", commission_rate: "0.0001", minimum_commission: "0", slippage_bps: "5" };
export const savedVersion = { id: 10, strategy_id: 1, algorithm_template_id: "range_breakout", name: "箱体突破", version: 1, instrument_code: "510500",
  template, settings, backtest_id: 1, comparison_id: 5, active: false, observation_id: 11, created_at: "2026-11-06T08:00:00Z" };
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
  input_sha256: "test-input-snapshot", complete: true, data_cutoff: "2026-11-06",
  note: "测试模板回测结果，不代表未来表现。",
  market_rows: candles.map(({ date, ...rest }) => ({ ...rest, trade_date: date })),
  tracks: [{ key: "template:range_breakout:1.0.0", backtest_id: 1, name: template.name, status: "success", template, allocation: 100, account: {
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
    if (path === "/account/holdings") return json(route, holdings);
    if (path === "/account/sync/status") return json(route, { latest: null, runs: [] });
    if (path.startsWith("/account/review/")) return json(route, { actual: { status: "not_applicable", reasons: ["测试：尚无可核算的真实成交"] },
      markers: [], start: settings.start_date, end: settings.end_date, quality: { issues: [] }, comparability: "测试数据不代表真实收益" });
    if (path === "/strategies/catalog") return json(route, catalog);
    if (path === "/strategies/comparisons") return json(route, request.method() === "POST" ? comparison : []);
    if (path === "/strategies") return json(route, request.method() === "POST" ? savedVersion : []);
    if (/\/strategies\/\d+\/enable/.test(path)) return json(route, { ...savedVersion, active: true });
    if (/\/strategies\/\d+\/pause/.test(path)) return json(route, { ...savedVersion, active: false });
    if (/\/strategies\/comparisons\/\d+$/.test(path)) return json(route, comparison);
    if (/\/strategies\/comparisons\/\d+\/verify$/.test(path)) return json(route, { identical: true });
    if (path === "/strategy-lab/signals" || path === "/strategy-lab/observations") return json(route, []);
    if (path.endsWith("/job") || path === "/job") return json(route, job);
    if (path === "/research/universe") return json(route, { items: instruments.map((item) => ({ ...item, held: true })), default_code: "510500" });
    if (path === "/research/object") return json(route, summary(url.searchParams.get("code") || "510500"));
    if (path.endsWith("/turning-events")) return json(route, { events: [], data_cutoff: null, partial: false });
    if (path.startsWith("/candles/")) return json(route, candles);
    if (path === "/backtests") return json(route, []);
    return json(route, { detail: `测试未配置接口：${request.method()} ${path}` }, 404);
  });
}

export const test = base.extend({ page: async ({ page }, use) => { await mockApi(page); await use(page); } });
export { expect };
