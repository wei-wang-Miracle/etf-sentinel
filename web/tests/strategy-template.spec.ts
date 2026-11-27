import { test, expect, catalog, comparison, assignment, json, settings } from "./fixtures";

const track = comparison.tracks[0];
const result = { ...comparison, complete: false, tracks: [
  { ...track, diagnostics: { completed_rounds: 2, open_rounds: 1, time_in_market: 0.8, rounds: [
    { entry_date: "2025-02-03", exit_date: "2025-03-03", pnl: "100.00" },
    { entry_date: "2025-04-01", exit_date: "2025-05-01", pnl: "-50.00" },
  ] } },
  { ...track, key: "strategy:bottom_confirmation", strategy_id: "bottom_confirmation", name: "底部确认", status: "failed", account: undefined, reason: "测试：缺少预热数据" },
  { ...track, key: "hold", strategy_id: "hold", name: "一直持有" },
] };

test("对比只提交策略身份，成功轨道经用户确认后才能采用", async ({ page }) => {
  let submitted: unknown, adopted: unknown;
  await page.route("**/api/strategies/comparisons", async (route) => {
    submitted = route.request().postDataJSON();
    return json(route, result);
  });
  await page.route("**/api/strategies/adopt", async (route) => {
    adopted = route.request().postDataJSON();
    return json(route, assignment);
  });
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await expect(page.getByRole("heading", { name: "策略回测" })).toBeVisible();
  await expect(page.getByLabel("初始研究资金（元）")).toHaveCount(0);
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  const table = page.getByRole("table", { name: "算法指标对照" });
  await expect(table.getByRole("row", { name: /轮次胜率/ })).toContainText("50.00%");
  await expect(table.getByText(/缺少预热/)).toBeVisible();
  expect(submitted).toEqual({ instrument_code: "510500", start_date: settings.start_date, end_date: settings.end_date,
    strategies: catalog.strategies.map(({ id }) => id) });
  await expect(table.getByRole("button", { name: /采用/ })).toHaveCount(1);
  await table.getByRole("button", { name: "采用箱体突破" }).click();
  expect(adopted).toBeUndefined();
  await page.getByRole("button", { name: "确认采用" }).click();
  await expect(table.getByRole("link", { name: /当前已采用/ })).toBeVisible();
  expect(adopted).toEqual({ comparison_id: 5, strategy_id: "range_breakout", replace_active: false });
});

test("变更区间及回看历史均不允许采用原回测", async ({ page }) => {
  await page.route("**/api/strategies/comparisons", (route) => json(route, result));
  await page.route("**/api/strategies/comparisons?*", (route) => json(route, [result]));
  await page.route("**/api/strategies/comparisons/5", (route) => json(route, result));
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("button", { name: "采用箱体突破" })).toBeVisible();
  await page.getByLabel("开始日期").fill("2025-02-04");
  await expect(page.getByText("研究范围已变更，请重新运行后再采用。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "采用箱体突破" })).toHaveCount(0);
  await page.getByText("历史回测", { exact: true }).click();
  await page.getByRole("button", { name: "查看回测 #5" }).click();
  await expect(page.getByRole("table", { name: "算法指标对照" })).toBeVisible();
  await expect(page.getByRole("button", { name: "采用箱体突破" })).toHaveCount(0);
});
