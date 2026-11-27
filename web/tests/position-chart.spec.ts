import type { Page } from "@playwright/test";
import { test, expect, comparison, json } from "./fixtures";

const days = comparison.market_rows.map((row) => row.trade_date);
const half = { ...comparison.tracks[0], name: "半资金测试", account: {
  ...comparison.tracks[0].account,
  daily: comparison.tracks[0].account.daily.filter((_, index) => index !== 5).map((row) => {
    const index = days.indexOf(row.trade_date);
    const weight = index === 0 || index === 4 ? 0 : index === 2 ? 0.49 : 0.48;
    return { ...row, position_weight: weight, quantity: weight ? 4800 : 0,
      equity: "50000", market_value: String(50000 * weight), cash: String(50000 * (1 - weight)) };
  }),
  trades: [
    { trade_date: days[1], signal_date: days[0], side: "buy", quantity: 4800, price: "5", commission: "2.4", slippage_cost: "0", reason: "测试买入" },
    { trade_date: days[4], signal_date: days[3], side: "sell", quantity: 4800, price: "5.2", commission: "2.5", slippage_cost: "0", reason: "测试清仓" },
  ],
} };
const full = { ...comparison.tracks[0], key: "full", name: "全资金测试", account: { ...comparison.tracks[0].account,
  daily: comparison.tracks[0].account.daily.map((row) => ({ ...row, position_weight: 0.98, quantity: 9800, equity: "50000", market_value: "49000", cash: "1000" })),
} };
const snapshot = { ...comparison, tracks: [half, full] };

async function openComparison(page: Page, value: unknown = snapshot) {
  await page.route("**/api/strategies/comparisons", (route) => json(route, value));
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("heading", { name: "半资金测试 · 模拟买卖点", exact: true })).toBeVisible();
}

// 读取真实图表实例，验证画布数据和联动；不增加生产测试接口。
async function chartState(page: Page, action?: Record<string, unknown>) {
  return page.locator(".kline").last().evaluate(async (element, action) => {
    const resource = performance.getEntriesByType("resource").find((entry) => entry.name.includes("echarts_core"));
    if (!resource) throw new Error("未找到已加载的图表模块");
    const echarts = await import(/* @vite-ignore */ resource.name);
    const chart = echarts.getInstanceByDom(element);
    if (action) chart.dispatchAction(action);
    const option = chart.getOption();
    return { series: option.series.map((row: { type: string; name: string; data: unknown[] }) => ({ type: row.type, name: row.name, data: row.data })),
      axes: option.yAxis.map((row: { min?: number; max?: number; name: string }) => ({ min: row.min, max: row.max, name: row.name })),
      markers: option.series[0].markPoint?.data ?? [],
      zoom: option.dataZoom.map((row: { xAxisIndex: number[]; start: number; end: number }) => ({ xAxisIndex: row.xAxisIndex, start: row.start, end: row.end })),
    };
  }, action);
}

test("仓位柱显示空仓、持续半仓及缺失日，固定百分比轴并联动缩放", async ({ page }) => {
  await openComparison(page);
  await expect(page.locator(".kline").last()).toHaveAttribute("aria-label", /每日收盘模拟仓位/);
  const state = await chartState(page);
  expect(state.series.some((row) => row.name === "成交量")).toBe(false);
  const bars = state.series.find((row) => row.name === "收盘模拟仓位");
  expect(bars?.type).toBe("bar");
  expect(bars?.data.slice(0, 6)).toEqual([0, 48, 49, 48, 0, null]);
  expect(state.axes[1]).toEqual({ min: 0, max: 100, name: "模拟仓位（%）" });
  const zoomed = await chartState(page, { type: "dataZoom", start: 10, end: 60 });
  expect(zoomed.zoom.every((row) => row.xAxisIndex.includes(0) && row.xAxisIndex.includes(1))).toBe(true);
  expect(zoomed.zoom[0].start).toBe(10);
  expect(zoomed.zoom[0].end).toBe(60);
});

test("悬停展示同日份额市值现金，缺失不冒充空仓", async ({ page }) => {
  await openComparison(page);
  await chartState(page, { type: "showTip", seriesIndex: 0, dataIndex: 1 });
  for (const text of ["收盘模拟仓位 48.00%", "持有份额 4,800 份", "持仓市值 24,000.00 元", "剩余现金 26,000.00 元"]) await expect(page.locator(".kline").last()).toContainText(text);
  await chartState(page, { type: "showTip", seriesIndex: 0, dataIndex: 4 });
  await expect(page.locator(".kline").last()).toContainText("0.00%（空仓）");
  await chartState(page, { type: "showTip", seriesIndex: 0, dataIndex: 5 });
  await expect(page.locator(".kline").last()).toContainText("缺失");
  await expect(page.locator(".kline").last()).not.toContainText("0.00%");
});

test("切换策略同步仓位，叠加真实标记不改模拟仓位，无成交仍显示账本", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("theme", "light"));
  await page.route("**/api/account/review/510500?*", (route) => json(route, {
    actual: { status: "not_applicable", reasons: ["隔离测试"] },
    markers: [{ trade_date: days[2], side: "buy", quantity: "100", price: "5.1" }], comparability: "隔离测试",
  }));
  await openComparison(page);
  await page.getByLabel("叠加真实操作").check();
  await expect.poll(async () => (await chartState(page)).markers.length).toBe(3);
  expect((await chartState(page)).series.find((row) => row.name === "收盘模拟仓位")?.data[1]).toBe(48);
  await page.getByRole("button", { name: "查看买卖点", exact: true }).nth(1).click();
  await expect(page.getByRole("heading", { name: "全资金测试 · 模拟买卖点", exact: true })).toBeVisible();
  expect((await chartState(page)).series.find((row) => row.name === "收盘模拟仓位")?.data[1]).toBe(98);
  await expect(page.getByText("这条策略在所选区间没有模拟成交。", { exact: true })).toBeVisible();
  expect((await chartState(page)).markers).toHaveLength(1);
  await page.locator(".kline").last().screenshot({ path: "/tmp/etf-position-chart-light.png" });
  await page.goto("/?page=etfs&code=510500");
  await expect(page.locator(".kline").first()).toHaveAttribute("aria-label", /成交量/);
});

for (const [theme, width] of [["light", 1440], ["dark", 390]] as const) {
  test(`缺少旧账本 ${theme} ${width} 保留缺失状态且无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.addInitScript((theme) => localStorage.setItem("theme", theme), theme);
    await openComparison(page, { ...snapshot, tracks: [{ ...half, account: { ...half.account, daily: [] } }] });
    await expect(page.getByText("模拟仓位账本缺失，无法展示每日仓位。", { exact: true })).toBeVisible();
    expect((await chartState(page)).series.find((row) => row.name === "收盘模拟仓位")?.data.every((value) => value === null)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.locator(".kline").last().screenshot({ path: `/tmp/etf-position-missing-${theme}.png` });
  });
}


test("旧快照缺少市值字段不推算，已有仓位及零现金仍可阅读", async ({ page }) => {
  const legacy = { ...half, account: { ...half.account, daily: half.account.daily.map(({ market_value: _marketValue, ...row }) => ({ ...row, cash: "0" })) } };
  await openComparison(page, { ...snapshot, tracks: [legacy] });
  await chartState(page, { type: "showTip", seriesIndex: 0, dataIndex: 1 });
  await expect(page.locator(".kline").last()).toContainText("持仓市值 缺失");
  await expect(page.locator(".kline").last()).toContainText("剩余现金 0.00 元");
  await expect(page.locator(".kline").last()).toContainText("48.00%");
});
