import { test, expect, assignment, catalog, json } from "./fixtures";

test("策略库只展示现行策略，说明页解释因子而不提供规则编辑", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500");
  const library = page.getByLabel("策略库", { exact: true });
  await expect(library.getByRole("heading")).toHaveText(["箱体突破", "底部确认", "复合反转"]);
  await expect(page.getByText(/还没有采用策略/)).toBeVisible();
  await page.goto("/?page=strategies&code=510500&view=algorithm&algorithm=bottom_confirmation");
  await expect(page.getByRole("heading", { name: "策略使用的因子" })).toBeVisible();
  await expect(page.getByText("阶段底部确认", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.getByRole("button", { name: "回测这套策略" }).click();
  await expect(page.getByRole("checkbox", { name: /底部确认/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /箱体突破/ })).not.toBeChecked();
});

test("暂停只影响指定ETF后续信号，仍可进入对比回测", async ({ page }) => {
  let active = true;
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, assignments: [
    { ...assignment, active }, { ...assignment, id: 11, instrument_code: "512100" },
  ] }));
  await page.route("**/api/strategies/510500/pause", (route) => {
    expect(route.request().method()).toBe("POST");
    active = false;
    return json(route, { ...assignment, active });
  });
  await page.goto("/?page=strategies&code=510500");
  const current = page.getByLabel("当前采用", { exact: true });
  await current.locator(".journey-saved-row").filter({ hasText: "510500" }).getByRole("button", { name: "暂停信号" }).click();
  await expect(current).toContainText("510500 · 箱体突破 · 已暂停");
  await expect(current).toContainText("512100 · 箱体突破 · 已启用");
  await current.locator(".journey-saved-row").filter({ hasText: "510500" }).getByRole("button", { name: "对比回测" }).click();
  await expect(page.getByRole("heading", { name: "策略回测" })).toBeVisible();
});
