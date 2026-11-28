import { test, expect, json, summary, assignment, catalog, candles } from "./fixtures";

const detailUrl = "/?page=etfs&code=510500&object=etf:510500&detail=overview&tab=price";

test("资金与份额默认显示份额流，国家队作为按需子视图", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/national-team/series/510500?*", (route) => {
    requests++;
    return json(route, { estimation_start_date: "2026-01-01", holdings: candles.map(row => ({ trade_date: row.date, estimated_holding_pct: 0 })), candles });
  });
  await page.goto(detailUrl);
  const tabs = page.getByRole("tablist", { name: "图表维度", exact: true });
  await expect(tabs.getByRole("tab")).toHaveCount(4);
  expect(requests).toBe(0);
  await tabs.getByRole("tab", { name: "行情", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "关联估值", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("img", { name: /ETF收盘价与近7日份额变动、收盘折溢价率/ })).toBeVisible();
  expect(requests).toBe(0);
  await page.getByRole("button", { name: "国家队估算", exact: true }).click();
  await expect(page.getByRole("img", { name: /国家队估算持仓比例同图双轴/ })).toBeVisible();
  await expect(page).toHaveURL(/tab=funds/);
  await page.reload();
  await expect(page.getByRole("tab", { name: "资金与份额", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText("0.00%", { exact: true })).toBeVisible();
});

test("常规口径提示收在图表下方，不占据指标与图表层级", async ({ page }) => {
  const warnings = ["行业恐贪仅作市场背景，未建立直接映射", "当前快照不是历史时点持仓；国家队比例不代表个人持仓"];
  await page.route("**/api/research/object?*", (route) => json(route, { ...summary(), warnings }));
  await page.goto(detailUrl);
  for (const warning of warnings) await expect(page.getByText(warning, { exact: true })).not.toBeVisible();
  await expect(page.locator(".dossier-research > .notice.warning")).toHaveCount(0);
  await page.getByText("数据来源与使用边界", { exact: true }).click();
  for (const warning of warnings) await expect(page.getByText(warning, { exact: true })).toBeVisible();
});

test("国家队源不支持的 ETF 明确说明原因，不诱导反复采集", async ({ page }) => {
  const data = summary();
  await page.route("**/api/research/object?*", (route) => json(route, { ...data, linked: { ...data.linked, national_team_tracked: false }, summary: { ...data.summary, national_team: { ratio: null, as_of: null } } }));
  await page.goto("/?page=etfs&code=510500&detail=overview&tab=funds&fund_view=national");
  await expect(page.getByRole("heading", { name: "该 ETF 不在国家队数据源范围内" })).toBeVisible();
  await expect(page.locator(".dossier-chart")).toContainText("仅提供18只ETF");
  await expect(page.locator(".dossier-chart")).toContainText("重新采集不会产生该标的数据");
  await expect(page.locator(".dossier-chart").getByRole("link", { name: "检查对应数据任务" })).toHaveCount(0);
});

test("国家队比例有数据而日 K 缺失时仍绘图，接口失败保留重试", async ({ page }) => {
  let available = false;
  await page.route("**/api/national-team/series/510500?*", (route) => json(route, available ? { estimation_start_date: "2026-01-01", holdings: [{ trade_date: "2026-11-06", estimated_holding_pct: 58.46 }], candles: [] } : { detail: "测试国家队接口失败" }, available ? 200 : 503));
  await page.goto("/?page=etfs&code=510500&detail=overview&tab=funds&fund_view=national");
  await expect(page.getByRole("alert")).toContainText("测试国家队接口失败");
  available = true;
  await page.getByRole("button", { name: "重试图表" }).click();
  await expect(page.getByRole("img", { name: /国家队估算持仓比例同图双轴/ })).toBeVisible();
  await expect(page.getByText(/区间缺少本地日 K/)).toBeVisible();
});

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

test("启用策略尚未生成信号时不能提示无策略", async ({ page }) => {
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, assignments: [assignment] }));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.getByText(/等待下一次运行/)).toBeVisible();
  await expect(page.getByText(/保存并启用一条策略后/)).toHaveCount(0);
});

test("未知仓位只给方向，历史计划与适用计划分开", async ({ page }) => {
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, assignments: [assignment] }));
  await page.route("**/api/strategy-lab/signals", (route) => json(route, [{ id: 20, instrument_code: "510500", assignment_id: assignment.id, strategy_id: assignment.strategy_id, strategy_name: "箱体突破",
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
  const target = "?page=strategies&code=512100&view=backtest";
  await page.goto(`/?page=data&manage=jobs&task=index-valuations&return_to=${encodeURIComponent(target)}`);
  await expect(page.getByRole("link", { name: /返回原任务/ })).toHaveAttribute("href", target);
});

test("有效零国家队比例不显示为缺失", async ({ page }) => {
  await page.route("**/api/research/object?**", (route) => json(route, summary()));
  await page.goto("/?page=etfs&code=510500&detail=overview&tab=funds&fund_view=national");
  await expect(page.getByText("0.00%", { exact: true })).toBeVisible();
});

test("策略状态刷新失败时旧计划不继续列为适用", async ({ page }) => {
  let unavailable = false;
  await page.route("**/api/strategies/catalog", route => json(route, unavailable ? { detail: "测试策略状态不可用" } : { ...catalog, assignments: [assignment] }, unavailable ? 503 : 200));
  await page.route("**/api/strategy-lab/signals", route => json(route, [{ id: 90, instrument_code: "510500", assignment_id: assignment.id, strategy_id: assignment.strategy_id, strategy_name: "箱体突破", execution_date: "2099-01-02", generated_at: "2026-11-06T00:00:00Z", data_cutoff: "2026-11-05", skip_note: null, plan: { action: "buy", actual_quantity: null, quantity_status: "unknown", reason: "测试旧计划", warnings: [] }, execution: { status: "pending", links: [] } }]));
  await page.route("**/api/strategy-lab/signals/generate", route => { unavailable = true; return json(route, { created: [], existing: [], blocked: [] }); });
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.getByText("测试旧计划", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "检查并生成盘前信号" }).click();
  await expect(page.getByText(/策略状态未取得/)).toBeVisible();
  await expect(page.getByText("测试旧计划", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await expect(page.getByText("测试旧计划", { exact: true })).toBeVisible();
});


test("每日信号按算法因子标签、满足状态和当时数值展示", async ({ page }) => {
  await page.route("**/api/strategy-lab/signals", (route) => json(route, [{ id: 21, instrument_code: "510500", assignment_id: assignment.id, strategy_id: assignment.strategy_id, strategy_name: "箱体突破",
    execution_date: "2020-01-02", generated_at: "2020-01-01T00:00:00Z", data_cutoff: "2019-12-31", skip_note: null,
    plan: { action: "buy", quantity_status: "unknown", actual_quantity: null, reason: "微观条件依据", warnings: [],
      conditions: { buy: [
        { label: "双均线交叉", satisfied: true, value: "1" },
        { label: "日成交量相对均量", satisfied: true, value: "1.5" },
      ], sell: [] } }, execution: { status: "pending", links: [] } }]));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await page.getByRole("button", { name: "历史记录", exact: true }).click();
  await page.getByText("算法因子状态与当时数值", { exact: true }).click();
  await expect(page.getByText("双均线交叉：满足；当时数值 1", { exact: true })).toBeVisible();
  await expect(page.getByText("日成交量相对均量：满足；当时数值 1.5", { exact: true })).toBeVisible();
});

test("每日信号显示算法名称，不显示算法版本号", async ({ page }) => {
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, assignments: [assignment] }));
  await page.route("**/api/strategy-lab/signals", (route) => json(route, [{ id: 91, instrument_code: "510500", assignment_id: assignment.id, strategy_id: assignment.strategy_id, strategy_name: "箱体突破",
    execution_date: "2099-01-02", generated_at: "2026-11-06T00:00:00Z", data_cutoff: "2099-01-01", skip_note: null,
    plan: { action: "wait", quantity_status: "unknown", actual_quantity: null, reason: "测试信号", warnings: [], indicators: { template_version: "1.0.0" } },
    execution: { status: "pending", links: [] } }]));
  await page.goto("/?page=etfs&code=510500&detail=signals");
  await expect(page.locator(".signal-version")).toHaveText("箱体突破");
  await expect(page.getByText(/第\d+版|1\.0\.0|算法模板版本/)).toHaveCount(0);
});

test("长区间叠加真实操作自动对齐同步起点，我的ETF列表提供查看行情直达入口", async ({ page }) => {
  let reviewUrl = "";
  await page.route("**/api/account/review/510500?*", (route) => {
    reviewUrl = route.request().url();
    return json(route, {
      actual: { status: "not_applicable", reasons: [] },
      markers: [{ trade_date: candles[10].date, side: "buy", quantity: "100", price: "5.1" }],
      start: "2025-01-20",
      end: candles.at(-1)!.date,
      quality: { issues: [] },
      comparability: "测试",
    });
  });
  await page.goto("/?page=etfs");
  const marketLink = page.locator(".journey-etf-row").first().getByRole("link", { name: "查看行情", exact: true });
  await expect(marketLink).toBeVisible();
  await marketLink.click();
  await expect(page).toHaveURL(/detail=overview.*tab=price|tab=price.*detail=overview/);

  await page.getByLabel("起始日期").fill("2023-11-28");
  await page.getByLabel("截止日期").fill(candles.at(-1)!.date);
  await page.getByLabel("叠加真实操作").check();
  await expect.poll(() => reviewUrl).toContain("start=2025-01-20");
  await expect(page.getByText(/真实操作仅叠加账户同步起点/)).toBeVisible();
});

test("无行业映射的ETF仍可观察全市场温度与波指", async ({ page }) => {
  await page.goto("/?page=etfs&code=510500&detail=overview&tab=sentiment&sentiment_scope=market");

  await expect(page.getByRole("button", { name: "全市场温度与波指", exact: true })).toBeVisible();
  await expect(page.getByText("全市场恐贪分", { exact: true })).toBeVisible();
  await expect(page.getByText("50ETF期权波动率", { exact: true })).toBeVisible();
  await expect(page.getByText(/子因子自 2025-11-28 起本地累积/)).toBeVisible();

  await page.getByRole("button", { name: "股债回报差", exact: true }).click();
  await expect(page.getByRole("img", { name: "全市场恐贪分数与股债回报差双轴历史图" })).toBeVisible();
  await page.getByRole("button", { name: "创新高占比", exact: true }).click();
  await expect(page.getByRole("img", { name: "全市场恐贪分数与创新高占比双轴历史图" })).toBeVisible();
});
