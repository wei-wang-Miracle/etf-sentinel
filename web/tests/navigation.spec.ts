import { test, expect, instruments, json, holdings } from "./fixtures";

test("主导航保留正在研究的ETF，不默选第一只", async ({ page }) => {
  await page.goto("/?page=etfs&code=512100&object=etf:512100&detail=overview");
  await page.getByRole("button", { name: "我的策略", exact: true }).click();
  await expect(page).toHaveURL(/code=512100/);
  await page.getByRole("button", { name: "开始策略对比" }).click();
  await expect(page.getByLabel("回测 ETF", { exact: true })).toHaveValue("512100");
});

test("完整同步的空持仓不会静默展示全部ETF", async ({ page }) => {
  await page.route("**/api/account/holdings", (route) => json(route, { ...holdings, items: [], summary: { holding_count: 0 } }));
  await page.goto("/?page=etfs");
  await expect(page.getByText("暂无当前持仓", { exact: true })).toBeVisible();
  await expect(page.locator(".journey-etf-row")).toHaveCount(0);
  await page.getByRole("button", { name: "全部 ETF", exact: true }).click();
  await expect(page.locator(".journey-etf-row")).toHaveCount(instruments.length);
});

test("账户读取失败不阻断全部ETF研究，也不标成未持仓", async ({ page }) => {
  await page.route("**/api/account/holdings", (route) => json(route, { detail: "测试账户不可用" }, 503));
  await page.goto("/?page=etfs&scope=all");
  await expect(page.locator(".journey-etf-row")).toHaveCount(instruments.length);
  await expect(page.getByText("持仓状态未取得").first()).toBeVisible();
  await expect(page.getByText("当前未持仓", { exact: true })).toHaveCount(0);
});

test("数据管理分类和任务在刷新后恢复", async ({ page }) => {
  await page.goto("/?page=data&manage=instruments");
  await page.getByRole("tab", { name: "账户与权益", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "账户与权益", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "任务与运行记录", exact: true }).click();
  await page.getByRole("tab", { name: "策略日计划", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("tab", { name: "策略日计划", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("业务Tab使用方向键且唯一当前项进入Tab序", async ({ page }) => {
  await page.goto("/?page=data&manage=instruments");
  const tab = page.getByRole("tab", { name: "标的配置", exact: true });
  await tab.focus(); await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "账户与权益", exact: true })).toBeFocused();
  await expect(page.getByRole("tab", { name: "账户与权益", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(tab).toHaveAttribute("tabindex", "-1");
});

test("没有对象时策略页要求选择，不自动选择配置第一只", async ({ page }) => {
  await page.goto("/?page=strategies");
  await page.getByRole("button", { name: "开始策略对比" }).click();
  await expect(page.getByLabel("回测 ETF", { exact: true })).toHaveValue("");
  await expect(page.getByText("先选择 ETF，再比较算法。", { exact: true })).toBeVisible();
});
