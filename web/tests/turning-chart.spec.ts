import type { Page } from "@playwright/test";
import { test, expect, factorCatalog, json } from "./fixtures";
import { reversalRows } from "./turning-fixtures";

const rows = reversalRows();
const start = rows[0].date;
const end = rows.at(-1)!.date;
const url = `/?page=etfs&code=510500&detail=overview&tab=price&start=${start}&end=${end}`;
const event = (index: number, factor: number) => ({ ...factorCatalog.factors[factor],
  factor_id: factorCatalog.factors[factor].id, trade_date: rows[index].date });

async function chartState(page: Page) {
  return page.locator(".kline").evaluate(async (element) => {
    const resource = performance.getEntriesByType("resource").find((entry) => entry.name.includes("echarts_core"));
    if (!resource) throw new Error("未找到图表模块");
    const echarts = await import(/* @vite-ignore */ resource.name);
    const chart = echarts.getInstanceByDom(element);
    const option = chart.getOption();
    return {
      markers: option.series[0].markPoint.data as { name: string; coord: [string, number] }[],
      dates: option.xAxis[0].data as string[],
    };
  });
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/candles/510500?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    expect(params.get("start")).toBe("1990-01-01");
    return json(route, rows.filter((row) => row.date <= params.get("end")!));
  });
  await page.route("**/api/candles/512100?*", (route) => json(route, rows));
});

test("行情默认展示阶段顶底与超跌后止跌修复，可叠加同日的收盘收复昨高与其他因子", async ({ page }) => {
  const events = [event(112, 0), event(112, 2), event(150, 6), event(150, 3), event(200, 1)];
  await page.route("**/api/candles/510500/factors?*", (route) => {
    const query = new URL(route.request().url()).searchParams;
    return json(route, {
      events: events.filter((item) => item.trade_date >= query.get("start")! && item.trade_date <= query.get("end")!),
      data_cutoff: query.get("end"),
      partial: false,
    });
  });
  await page.route("**/api/candles/512100/factors?*", (route) => json(route, {
    events: [event(140, 1)],
    data_cutoff: rows[190].date,
    partial: true,
  }));

  await page.goto(url);
  await expect(page.getByLabel("顶底来源")).toHaveCount(0);
  await expect.poll(async () => (await chartState(page)).markers.map((marker) => ({ name: marker.name, coord: marker.coord }))).toEqual([
    { name: "阶段底部确认", coord: [rows[112].date, rows[112].low] },
    { name: "超跌后止跌修复", coord: [rows[150].date, rows[150].low] },
    { name: "阶段顶部确认", coord: [rows[200].date, rows[200].high] },
  ]);
  await page.getByText(/因子标记 · 已选/).click();
  await page.getByRole("checkbox", { name: /放量向上突破/ }).check();
  await page.getByRole("checkbox", { name: /收盘收复昨高/ }).check();
  await expect.poll(async () => (await chartState(page)).markers.filter((marker) => marker.coord[0] === rows[112].date).map((marker) => marker.name)).toEqual(["阶段底部确认", "放量向上突破"]);
  await expect.poll(async () => (await chartState(page)).markers.filter((marker) => marker.coord[0] === rows[150].date).map((marker) => marker.name)).toEqual(["超跌后止跌修复", "收盘收复昨高"]);
  await page.getByRole("checkbox", { name: /底部确认/ }).uncheck();
  await expect.poll(async () => (await chartState(page)).markers.map((marker) => marker.name)).toEqual(["放量向上突破", "超跌后止跌修复", "收盘收复昨高", "阶段顶部确认"]);
  await page.getByLabel("当前 ETF").selectOption("512100");
  await expect(page.getByText(/部分行情日期尚未核验权益/)).toBeVisible();
  await expect.poll(async () => (await chartState(page)).markers.map((marker) => marker.coord[0])).toEqual([rows[140].date]);
});

test("顶底接口失败时保留日K但不回退到本地实验算法", async ({ page }) => {
  let requests = 0;
  let verified = false;
  let runs: unknown[] = [];
  await page.route("**/api/candles/510500/factors?*", async (route) => {
    requests += 1;
    if (!verified) {
      if (requests > 1) await new Promise((resolve) => setTimeout(resolve, 500));
      await json(route, { detail: "尚无已核验权益资料" }, 422);
      return;
    }
    await json(route, { events: [event(112, 0)], data_cutoff: end, partial: false });
  });
  await page.route("**/api/job", (route) => json(route, {
    enabled: true, time: "01:00", next_run: null, source_configured: true, runs,
  }));
  await page.route("**/api/job/run", async (route) => {
    verified = true;
    runs = [{
      id: 7, status: "success", trigger: "manual", started_at: "2026-11-25T00:00:00Z",
      ended_at: "2026-11-25T00:01:00Z", logs: [{
        kind: "equity", code: "510500", status: "success", count: 0,
        message: "已核验：现金分红 0 项，份额折算 0 项",
      }],
    }];
    await json(route, { run_id: 7 }, 202);
  });

  await page.goto(url);
  await expect(page.getByRole("status")).toContainText("尚无已核验权益资料");
  await expect(page.locator(".kline")).toBeVisible();
  expect((await chartState(page)).markers).toEqual([]);
  await expect(page.getByLabel("顶底来源")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "到行情任务批量更新权益资料", exact: true })).toHaveAttribute("href", /page=data.*manage=jobs.*code=510500.*task=etf/);

  const beforeRetry = requests;
  const retried = page.waitForRequest((request) => request.url().includes("/api/candles/510500/factors"));
  await page.getByRole("button", { name: "重试标点", exact: true }).click();
  await retried;
  await expect(page.getByRole("status")).toContainText("正在读取因子标记");
  await expect(page.getByRole("status")).toContainText("尚无已核验权益资料");
  expect(requests).toBe(beforeRetry + 1);

  await page.getByRole("link", { name: "到行情任务批量更新权益资料", exact: true }).click();
  await expect(page).toHaveURL(/page=data.*manage=jobs.*code=510500.*task=etf/);
  await expect(page.getByRole("heading", { name: "基金日行情与权益资料核验" })).toBeVisible();
  await page.getByRole("button", { name: "立即采集", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已启动");
  await page.getByRole("button", { name: "查看日志", exact: true }).click();
  await expect(page.getByText("权益资料 · 510500", { exact: true })).toBeVisible();
  await expect(page.getByText("已核验：现金分红 0 项，份额折算 0 项", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "返回原任务 · 510500", exact: true }).click();
  await expect(page).toHaveURL(/page=etfs.*code=510500/);
  await expect.poll(async () => (await chartState(page)).markers.map((marker) => marker.name)).toEqual(["阶段底部确认"]);
});

test("因子标记展开为浮层不推挤日K，支持标签移除与Esc关闭", async ({ page }) => {
  await page.route("**/api/candles/510500/factors?*", (route) =>
    json(route, { events: [event(112, 0), event(200, 1)], data_cutoff: end, partial: false }),
  );
  await page.goto(url);
  const chart = page.getByRole("img", { name: /基金日K/ });
  await expect(chart).toBeVisible();
  const beforeY = (await chart.boundingBox())!.y;

  const trigger = page.getByRole("button", { name: /因子标记 · 已选 3 项/ });
  await trigger.click();
  await expect(page.getByRole("dialog", { name: "选择因子标记" })).toBeVisible();
  expect((await chart.boundingBox())!.y).toBe(beforeY);
  await page.screenshot({ path: "/tmp/etf-factor-popover.png" });

  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "选择因子标记" })).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.getByRole("button", { name: "移除 阶段底部确认" }).click();
  await expect(page.getByRole("button", { name: /因子标记 · 已选 2 项/ })).toBeVisible();
  await expect.poll(async () => (await chartState(page)).markers.map((marker) => marker.name)).toEqual(["阶段顶部确认"]);
});

test("因子图层按业务分类分组，并提示缺少指数映射的外部背景", async ({ page }) => {
  await page.route("**/api/candles/510500/factors?*", (route) =>
    json(route, {
      events: [], data_cutoff: end, partial: false,
      external_factor_context: {
        valuation_index_codes: [],
        coverage: { valuation: { available: false } },
        benchmark: { available: false },
      },
    }),
  );

  await page.goto(url);
  await page.getByRole("button", { name: /因子标记 · 已选 3 项/ }).click();
  await expect(page.getByRole("group", { name: "结构确认" })).toBeVisible();
  await expect(page.getByRole("group", { name: "外部估值" })).toBeVisible();
  await expect(page.getByRole("group", { name: "相对强弱" })).toBeVisible();
  await page.getByRole("checkbox", { name: /股债高性价比保护/ }).check();
  await expect(page.getByText("该 ETF 尚未映射指数，外部估值及相对强弱标记不可用")).toBeVisible();
});

test("行情缺少交易日报错时不误导更新权益资料", async ({ page }) => {
  await page.route("**/api/candles/510500/factors?*", (route) =>
    json(route, { detail: "行情数据未通过校验：行情缺少交易日（首日 2025-05-06，共 1 日未核验停牌），拒绝回测" }, 422),
  );
  await page.goto(url);
  await expect(page.getByRole("status")).toContainText("行情数据未通过校验");
  await expect(page.getByRole("link", { name: "到行情任务核验并补全行情", exact: true })).toHaveAttribute("href", /page=data.*manage=jobs.*code=510500.*task=etf/);
  await expect(page.getByRole("link", { name: "到行情任务批量更新权益资料", exact: true })).toHaveCount(0);
});
