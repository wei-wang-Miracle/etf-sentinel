import type { Page } from "@playwright/test";
import { test, expect, json } from "./fixtures";
import { reversalRows } from "./turning-fixtures";
import { calculateTurningPoints } from "../src/lib/turningPoints";
import { turningProfile } from "../src/lib/turningCategories";

const rows = reversalRows();
const profile = turningProfile("510500");
const expected = calculateTurningPoints(rows, profile.options);
const start = rows[0].date, end = rows.at(-1)!.date;
const url = `/?page=etfs&code=510500&detail=overview&tab=price&start=${start}&end=${end}`;

async function chartState(page: Page, action?: Record<string, unknown>) {
  return page.locator(".kline").evaluate(async (element, action) => {
    const resource = performance.getEntriesByType("resource").find(entry => entry.name.includes("echarts_core"));
    if (!resource) throw new Error("未找到图表模块");
    const echarts = await import(/* @vite-ignore */ resource.name);
    const chart = echarts.getInstanceByDom(element);
    if (action) chart.dispatchAction(action);
    const option = chart.getOption();
    return { markers: option.series[0].markPoint.data as { name: string; coord: [string, number]; symbol: string }[],
      ma20: option.series.find((series: { name: string }) => series.name === "MA20")?.data as (number | null)[],
      dates: option.xAxis[0].data as string[], zoom: { start: option.dataZoom[0].start, end: option.dataZoom[0].end } };
  }, action);
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/candles/510500?*", route => {
    const params = new URL(route.request().url()).searchParams;
    expect(params.get("start")).toBe("1990-01-01");
    return json(route, rows.filter(row => row.date <= params.get("end")!));
  });
});

test("两类标记落在确认日，开关独立并与真实操作共存", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/account/review/510500?*", route => json(route, { markers: [{ trade_date: expected.signals[0].date, side: "buy", quantity: "100", price: "8.8" }] }));
  await page.goto(url);
  await expect(page.locator(".kline")).toBeVisible();
  expect((await chartState(page)).markers.map(marker => marker.coord[0])).toEqual(expected.signals.map(signal => signal.date));
  expect((await chartState(page)).markers.map(marker => marker.name)).toEqual(["底部确认", "顶部确认"]);
  await page.getByRole("checkbox", { name: /底部确认/ }).uncheck();
  expect((await chartState(page)).markers.map(marker => marker.name)).toEqual(["顶部确认"]);
  await page.getByLabel("叠加真实操作", { exact: true }).check();
  await expect.poll(async () => (await chartState(page)).markers.length).toBe(2);
  await page.getByRole("checkbox", { name: /顶部确认/ }).uncheck();
  expect((await chartState(page)).markers.map(marker => marker.name)).toEqual(["实际（委托日）买入"]);
  expect(errors).toEqual([]);
});

test("悬停和键盘读数保留依据，历史检验可换周期，不受开关影响", async ({ page }) => {
  await page.goto(url);
  await expect(page.locator(".kline")).toBeVisible();
  const signal = expected.signals[0];
  const index = rows.findIndex(row => row.date === signal.date);
  await chartState(page, { type: "showTip", seriesIndex: 0, dataIndex: index });
  await expect(page.locator(".kline")).toContainText("连续");
  await page.getByText("键盘日期读数", { exact: true }).click();
  await page.getByLabel("读数日期").selectOption(signal.date);
  await expect(page.locator(".chart-readout .readout-values")).toContainText("底部确认");
  await expect(page.locator(".chart-readout .readout-values")).toContainText("失效参考价");
  await page.getByText("顶底指标 · 规则与历史检验（实验）", { exact: true }).click();
  await expect(page.locator(".turning-evaluation")).toContainText("中盘宽基");
  await expect(page.locator(".turning-evaluation")).toContainText("未达80%验证目标");
  const stats = page.getByRole("region", { name: "底部确认历史检验", exact: true });
  await expect(stats).toContainText("1 / 1");
  await expect(stats).toContainText("100.0%");
  await page.getByLabel("确认后观察期").selectOption("20");
  await expect(page.locator(".turning-evaluation")).toContainText("第20个交易日");
  await page.getByRole("checkbox", { name: /底部确认/ }).uncheck();
  await expect(stats).toContainText("1 / 1");
});

test("修改显示起点保持同日标记和MA20，截止日前不足观察期不计命中", async ({ page }) => {
  await page.goto(url);
  await expect(page.locator(".kline")).toBeVisible();
  const before = await chartState(page);
  await page.getByLabel("起始日期", { exact: true }).fill(rows[110].date);
  const after = await chartState(page);
  expect(after.markers).toEqual(before.markers);
  expect(after.dates[0]).toBe(rows[110].date);
  expect(after.ma20[0]).toBe(before.ma20[110]);
  await page.getByLabel("截止日期", { exact: true }).fill(expected.signals[0].date);
  await expect.poll(async () => (await chartState(page)).markers.length).toBe(1);
  await page.getByText("顶底指标 · 规则与历史检验（实验）", { exact: true }).click();
  const stats = page.getByRole("region", { name: "底部确认历史检验", exact: true });
  await expect(stats).toContainText("0 / 0");
  await expect(stats).toContainText("1 / 0");
});

test("局部缩放后切换指标与观察期保留视图", async ({ page }) => {
  await page.goto(url);
  await expect(page.locator(".kline")).toBeVisible();
  const zoom = (await chartState(page, { type: "dataZoom", start: 25, end: 75 })).zoom;
  await page.getByRole("checkbox", { name: /底部确认/ }).uncheck();
  expect((await chartState(page)).zoom).toEqual(zoom);
  await page.getByText("顶底指标 · 规则与历史检验（实验）", { exact: true }).click();
  await page.getByLabel("确认后观察期").selectOption("5");
  expect((await chartState(page)).zoom).toEqual(zoom);
});

test("不足预热、无行情和接口错误分别展示，可重试", async ({ page }) => {
  let mode = "short";
  await page.route("**/api/candles/510500?*", route => json(route, mode === "short" ? rows.slice(0, 30) : mode === "empty" ? [] : { detail: "测试行情读取失败" }, mode === "error" ? 503 : 200));
  await page.goto(url);
  await expect(page.getByText(/连续有效行情不足60条/)).toBeVisible();
  expect((await chartState(page)).markers).toEqual([]);
  mode = "empty";
  await page.reload();
  await expect(page.getByRole("heading", { name: "所选区间暂无数据" })).toBeVisible();
  mode = "error";
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("测试行情读取失败");
  mode = "short";
  await page.getByRole("button", { name: "重试图表", exact: true }).click();
  await expect(page.locator(".kline")).toBeVisible();
});

for (const [theme, width] of [["light", 1440], ["dark", 390]] as const) {
  test(`顶底图表与检验 ${theme} ${width} 无溢出`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(theme => localStorage.setItem("theme", theme), theme);
    await page.goto(url);
    await expect(page.locator(".kline")).toBeVisible();
    expect((await chartState(page)).markers).toHaveLength(2);
    const box = (await page.locator(".kline").boundingBox())!;
    expect(box.y).toBeLessThanOrEqual(width === 390 ? 640 : 360);
    await page.getByText("顶底指标 · 规则与历史检验（实验）", { exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({ path: `/tmp/etf-turning-${theme}-${width}.png`, fullPage: true });
  });
}
