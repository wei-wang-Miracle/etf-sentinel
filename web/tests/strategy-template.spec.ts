import { test, expect, catalog, comparison, json, savedVersion, settings, template } from "./fixtures";

const result = {
  ...comparison,
  tracks: [
    { ...comparison.tracks[0], key: "template:range_breakout:1.0.0", name: template.name, backtest_id: 1,
      diagnostics: { completed_rounds: 2, open_rounds: 1, rounds: [
        { entry_date: "2025-02-03", exit_date: "2025-03-03", pnl: "100.00" },
        { entry_date: "2025-04-01", exit_date: "2025-05-01", pnl: "-50.00" },
      ], time_in_market: 0.8 } },
    { ...comparison.tracks[0], key: "template:bottom_confirmation:1.0.0", name: "底部确认", status: "failed", template: { ...template, id: "bottom_confirmation" }, account: undefined, reason: "测试：缺少预热数据" },
    { ...comparison.tracks[0], key: "hold", name: "一直持有", template: undefined },
  ],
  complete: false,
};

test("比较两套算法后只绑定成功且选中的结果，随后显式启用", async ({ page }) => {
  let submitted: unknown, binding: unknown, enabled: unknown;
  let items: (typeof savedVersion)[] = [];
  await page.route("**/api/strategies/comparisons", async (route) => {
    submitted = route.request().postDataJSON();
    await json(route, result);
  });
  await page.route("**/api/strategies/comparisons/5", (route) => json(route, result));
  await page.route("**/api/strategies", async (route) => {
    if (route.request().method() === "POST") {
      binding = route.request().postDataJSON();
      items = [{ ...savedVersion, comparison_id: 5 }];
      return json(route, items[0]);
    }
    return json(route, items);
  });
  await page.route("**/api/strategies/10/enable", async (route) => {
    enabled = route.request().postDataJSON();
    items = [{ ...items[0], active: true }];
    await json(route, items[0]);
  });
  await page.goto("/?page=strategies&code=510500&view=editor&stage=compare");
  await expect(page.getByRole("heading", { name: "算法回测" })).toBeVisible();
  await expect(page.getByLabel("策略名称")).toHaveCount(0);
  await expect(page.getByLabel("初始研究资金（元）")).toHaveCount(0);
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  const table = page.getByRole("table", { name: "算法指标对照" });
  await expect(table.getByRole("row", { name: /轮次胜率/ })).toContainText("50.00%");
  await expect(table.getByRole("row", { name: /已完成轮次/ })).toContainText("2");
  await expect(table.getByRole("row", { name: /未平仓轮次/ })).toContainText("1");
  await expect(table.getByText(/缺少预热/)).toBeVisible();
  expect(submitted).toEqual({ instrument_code: "510500", start_date: settings.start_date, end_date: settings.end_date,
    templates: catalog.templates.map(({ id, version }) => ({ id, version })) });
  expect(binding).toBeUndefined();
  await expect(table.getByRole("button", { name: /保存并绑定/ })).toHaveCount(1);
  await table.getByRole("button", { name: "保存并绑定箱体突破" }).click();
  expect(binding).toEqual({ comparison_id: 5, track_key: "template:range_breakout:1.0.0" });
  expect(enabled).toBeUndefined();
  await page.getByRole("link", { name: "查看箱体突破绑定" }).click();
  await page.getByRole("button", { name: "启用每日信号", exact: true }).click();
  await page.getByRole("button", { name: "确认启用", exact: true }).click();
  expect(enabled).toEqual({ replace_active: false });
  await expect(page.getByRole("status").filter({ hasText: /已启用/ })).toBeVisible();
});

test("变更回测区间后旧结果不可用于绑定，可回看原计算", async ({ page }) => {
  await page.route("**/api/strategies/comparisons", (route) => json(route, result));
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("button", { name: "保存并绑定箱体突破" })).toBeVisible();
  await page.getByLabel("开始日期").fill("2025-02-04");
  await expect(page.getByText("研究范围已变更，请重新运行后再保存。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "保存并绑定箱体突破" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "算法指标对照" })).toBeVisible();
});
