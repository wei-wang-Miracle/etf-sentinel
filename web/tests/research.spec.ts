import { test, expect, json, summary, savedVersion } from "./fixtures";

const detailUrl = "/?page=etfs&code=510500&object=etf:510500&detail=overview&tab=price";

test("ETF详情只有一个标题和对象选择器，图表进入首屏", async ({ page }) => {
  await page.goto(detailUrl);
  await expect(page.locator("main h1")).toHaveCount(1);
  await expect(page.getByLabel("当前 ETF", { exact: true })).toHaveCount(1);
  const chart = page.getByRole("img", { name: /基金日K/ });
  await expect(chart).toBeVisible();
  expect((await chart.boundingBox())!.y).toBeLessThanOrEqual(360);
});

test("390像素下图表保留至少350像素宽，主导航带文字", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(detailUrl);
  const chart = page.getByRole("img", { name: /基金日K/ });
  await expect(chart).toBeVisible();
  const box = (await chart.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(350);
  expect(box.y).toBeLessThanOrEqual(640);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await expect(page.locator("nav .nav-text").first()).toBeVisible();
});

test("日K提供可键盘操作的日期读数，不能只靠悬停", async ({ page }) => {
  await page.goto(detailUrl);
  await page.getByText("键盘日期读数", { exact: true }).click();
  const select = page.getByLabel("读数日期", { exact: true });
  await expect(select).toBeVisible();
  const last = await select.inputValue();
  await page.getByRole("button", { name: "上一日", exact: true }).click();
  await expect(select).not.toHaveValue(last);
  await expect(page.getByText(/收盘（元）/).last()).toBeVisible();
});

test("启用策略尚未生成信号时不能提示无策略", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [{ ...savedVersion, active: true }]));
  await page.route("**/api/strategy-lab/observations", (route) => json(route, [{ id: 11, instrument_code: "510500", active: true, rule: { name: "测试趋势" } }]));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.getByText(/等待下一次运行/)).toBeVisible();
  await expect(page.getByText(/保存并启用一条策略后/)).toHaveCount(0);
});

test("未知仓位只给方向，历史计划与适用计划分开", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [{ ...savedVersion, active: true }]));
  await page.route("**/api/strategy-lab/observations", (route) => json(route, [{ id: 11, instrument_code: "510500", active: true, rule: { name: "测试趋势" } }]));
  await page.route("**/api/strategy-lab/signals", (route) => json(route, [{ id: 20, instrument_code: "510500", observation_id: 11,
    execution_date: "2020-01-02", generated_at: "2020-01-01T00:00:00Z", data_cutoff: "2019-12-31", skip_note: null,
    plan: { action: "buy", actual_quantity: null, available_quantity: null, quantity_status: "unknown", target_quantity: null,
      reason: "测试仓位未知", funding_check_required: true, warnings: [] }, execution: { status: "pending", links: [] } }]));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.getByText("测试仓位未知")).toHaveCount(0);
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await expect(page.getByText("测试仓位未知")).toBeVisible();
  await expect(page.getByText("数量待核验", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/这是历史计划/)).toBeVisible();
  await expect(page.getByText("核对真实累计委托／主动跳过", { exact: true })).toHaveCount(0);
});

test("数据管理返回目标只允许内部页面", async ({ page }) => {
  await page.goto("/?page=data&manage=jobs&return_to=https%3A%2F%2Fevil.example%2F");
  await expect(page.getByRole("link", { name: /返回原任务/ })).toHaveCount(0);
  const target = "?page=strategies&code=512100&view=editor&stage=compare";
  await page.goto(`/?page=data&manage=jobs&task=index-valuations&return_to=${encodeURIComponent(target)}`);
  await expect(page.getByRole("link", { name: /返回原任务/ })).toHaveAttribute("href", target);
});

test("有效零国家队比例不显示为缺失", async ({ page }) => {
  await page.route("**/api/research/object?**", (route) => json(route, summary()));
  await page.goto("/?page=etfs&code=510500&detail=overview&tab=funds");
  await expect(page.getByText("0.00%", { exact: true })).toBeVisible();
});

test("策略状态刷新失败时旧计划不继续列为适用", async ({ page }) => {
  let unavailable = false;
  await page.route("**/api/strategies", route => json(route, unavailable ? { detail: "测试版本状态不可用" } : [{ ...savedVersion, active: true }], unavailable ? 503 : 200));
  await page.route("**/api/strategy-lab/observations", route => json(route, [{ id: 11, instrument_code: "510500", active: true, rule: { name: "测试趋势" } }]));
  await page.route("**/api/strategy-lab/signals", route => json(route, [{ id: 90, instrument_code: "510500", observation_id: 11, execution_date: "2099-01-02", generated_at: "2026-11-06T00:00:00Z", data_cutoff: "2026-11-05", skip_note: null, plan: { action: "buy", actual_quantity: null, quantity_status: "unknown", reason: "测试旧计划", warnings: [] }, execution: { status: "pending", links: [] } }]));
  await page.route("**/api/strategy-lab/signals/generate", route => { unavailable = true; return json(route, { created: [], existing: [], blocked: [] }); });
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.getByText("测试旧计划", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "检查并生成盘前信号" }).click();
  await expect(page.getByText(/部分策略状态未取得/)).toBeVisible();
  await expect(page.getByText("测试旧计划", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await expect(page.getByText("测试旧计划", { exact: true })).toBeVisible();
});


test("每日信号依据展示事件方向与均线窗口，数值条件保留单位", async ({ page }) => {
  await page.route("**/api/strategy-lab/signals", (route) => json(route, [{ id: 21, instrument_code: "510500", observation_id: 11,
    execution_date: "2020-01-02", generated_at: "2020-01-01T00:00:00Z", data_cutoff: "2019-12-31", skip_note: null,
    plan: { action: "buy", quantity_status: "unknown", actual_quantity: null, reason: "微观条件依据", warnings: [],
      conditions: { buy: [
        { indicator: "ma_cross", label: "双均线交叉", window: 5, long_window: 20, operator: "cross_down", threshold: "0", satisfied: true, value: "1", unit: "事件" },
        { indicator: "volume_ratio", label: "日成交量相对均量", window: 5, operator: "gt", threshold: "1.2", satisfied: true, value: "1.5", unit: "倍" },
      ], sell: [] } }, execution: { status: "pending", links: [] } }]));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await page.getByText("逐条条件与当时数值", { exact: true }).click();
  await expect(page.getByText("双均线交叉（短5／长20日）下穿：满足；事件发生", { exact: true })).toBeVisible();
  await expect(page.getByText("日成交量相对均量（5个交易日）高于1.2倍：满足；当时数值 1.5倍", { exact: true })).toBeVisible();
});
