import { test, expect, catalog, savedVersion, json } from "./fixtures";

test("算法库按算法展示多个 ETF 的绑定", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion, {
    ...savedVersion, id: 11, strategy_id: 2, instrument_code: "512100", active: true,
  }]));
  await page.goto("/?page=strategies");
  await expect(page.getByRole("heading", { name: "策略算法库" })).toBeVisible();
  const card = page.locator(".algorithm-card").filter({ has: page.getByRole("heading", { name: "箱体突破" }) });
  await expect(card.getByRole("heading", { name: "已绑定 2 只 ETF" })).toBeVisible();
  await expect(card.getByText("510500")).toBeVisible();
  await expect(card.getByText("512100")).toBeVisible();
  await card.getByRole("button", { name: "回测箱体突破" }).click();
  await expect(page.getByLabel("回测 ETF")).toHaveValue("");
  await page.getByLabel("回测 ETF").selectOption("512100");
  await expect(page.getByRole("checkbox", { name: /箱体突破/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /底部确认/ })).not.toBeChecked();
});

test("算法库显示简述并能打开当前算法的详细说明", async ({ page }) => {
  await page.goto("/?page=strategies");
  const card = page.locator(".algorithm-card").filter({ has: page.getByRole("heading", { name: "箱体突破" }) });
  await expect(card.getByText(/版本/)).toHaveCount(0);
  await expect(card.getByText("箱体突破的测试规则")).toBeVisible();
  await card.getByRole("link", { name: "算法说明" }).click();
  await expect(page.getByRole("heading", { name: "箱体突破算法说明" })).toBeVisible();
  await expect(page.getByText("回测这套算法", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "指标定义与市场含义" })).toBeVisible();
  await expect(page.getByText("当日含息收盘指数高于此前 20 个交易日的最高收盘指数。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "买入与退出规则" })).toBeVisible();
  await expect(page.getByText("买入结构必须成立，四项核心条件至少满足三项。", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "迭代与复核" })).toBeVisible();
});

test("算法说明展示当前 ETF 绑定的统一顶底参数模板", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500&view=algorithm&algorithm=range_breakout");
  await expect(page.getByRole("heading", { name: "统一顶底确认因子", exact: true })).toBeVisible();
  await expect(page.locator(".algorithm-guide")).toContainText("中盘");
  await expect(page.locator(".algorithm-guide")).toContainText("同一因果事件引擎");
});

test("三套算法说明分别解释各自的入场结构", async ({ page }) => {
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, templates: [...catalog.templates, {
    id: "hybrid_reversal", version: "1.0.0", name: "复合反转", status: "experimental",
    description: "复合结构测试说明", supported_instruments: ["510500", "512100"], note: "测试说明",
  }] }));
  await page.goto("/?page=strategies&view=algorithm&algorithm=range_breakout");
  await page.getByRole("link", { name: "底部确认", exact: true }).click();
  await expect(page.getByText("最近 5 个交易日内出现一次因果确认的底部事件。")).toBeVisible();
  await page.getByRole("link", { name: "复合反转", exact: true }).click();
  await expect(page.getByText("最近 5 日内出现底部确认事件，或 RSI14 不高于 35，或价格低于 20 日均线至少 2%；三者任一成立即可进入其他条件核验。")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator("body").evaluate((node) => node.scrollWidth)).toBeLessThanOrEqual(390);
  await expect.poll(() => page.locator(".algorithm-guide-table").evaluate((node) => node.scrollWidth)).toBeLessThanOrEqual(await page.locator(".algorithm-guide-table").evaluate((node) => node.clientWidth));
});

test("第四套算法可参与比较，说明页按 ETF 展示原研究规则", async ({ page }) => {
  const rule = { family: "oversold", slow: 120, trend_floor: .02, volume_min: 1, recovery: 5,
    rsi_window: 14, rsi_buy: 10, dip: .02, event_age: 2, buy_votes: 3, sell_votes: 2,
    exit_ma: 10, rsi_sell: 70, stop_loss: .04, take_profit: .06, trailing: .05,
    max_holding: 40, cooldown: 3, value_metric: "none", value_max: 80 };
  await page.route("**/api/strategies/catalog", (route) => json(route, { ...catalog, templates: [...catalog.templates, {
    ...catalog.templates[0], id: "hybrid_reversal", name: "复合反转", description: "复合结构测试说明",
  }, {
    ...catalog.templates[0], id: "etf_multifactor", name: "ETF多因子择时（实验）", description: "复用 50 轮历史研究的逐 ETF 规则。",
    rules_by_instrument: { "510500": rule, "512100": { ...rule, family: "bottom", event_age: 5, slow: 40 } },
  }] }));
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await expect(page.getByRole("checkbox")).toHaveCount(4);
  const multifactor = page.locator(".algorithm-pick-entry").filter({ has: page.getByRole("checkbox", { name: /多因子择时/ }) });
  await expect(multifactor.getByRole("checkbox")).toBeChecked();
  await expect(multifactor.getByText(/逐 ETF 规则/)).toBeVisible();
  const request = page.waitForRequest((candidate) => candidate.method() === "POST" && candidate.url().endsWith("/strategies/comparisons"));
  await page.getByRole("button", { name: "运行回测" }).click();
  expect((await request).postDataJSON().templates.map(({ id }: { id: string }) => id)).toEqual([
    "range_breakout", "bottom_confirmation", "hybrid_reversal", "etf_multifactor",
  ]);
  await multifactor.getByRole("link", { name: "算法说明" }).click();
  await expect(page.getByRole("heading", { name: /多因子择时.*算法说明/ })).toBeVisible();
  await expect(page.getByText(/120 日均线偏离/)).toBeVisible();
  await page.getByLabel("查看 ETF 规则").selectOption("512100");
  await expect(page.getByText(/40 日均线偏离/)).toBeVisible();
  await page.getByRole("link", { name: "回测这套算法" }).click();
  await expect(page.getByLabel("回测 ETF")).toHaveValue("512100");
  await expect(page.getByRole("checkbox", { name: /多因子择时/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /箱体突破/ })).not.toBeChecked();
});

test("算法选择项提供当前算法说明，比较结果不展示冻结参数块", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500&view=backtest");
  const option = page.locator(".algorithm-pick-entry").filter({ has: page.getByRole("checkbox", { name: /箱体突破/ }) });
  await expect(option.getByText("版本 1.0.0")).toHaveCount(0);
  await expect(option.getByText("箱体突破的测试规则")).toBeVisible();
  await option.getByRole("link", { name: "算法说明" }).click();
  await expect(page).toHaveURL(/view=algorithm/);
  await expect(page.getByRole("heading", { name: "箱体突破算法说明" })).toBeVisible();
  await page.getByRole("button", { name: "返回算法库" }).click();
  await page.getByRole("button", { name: "开始算法对比" }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("table", { name: "算法指标对照" })).toBeVisible();
  await expect(page.getByText(/冻结模板依据|固定版本/)).toHaveCount(0);
  await expect(page.getByText("本次计算依据", { exact: true })).toHaveCount(0);
  await expect(page.locator(".journey-digest")).toHaveCount(0);
});

test("算法库与每日信号入口可互相返回", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500");
  await page.getByRole("link", { name: "查看每日信号", exact: true }).click();
  await expect(page).toHaveURL(/page=etfs/);
  await expect(page).toHaveURL(/detail=signals/);
  await expect(page.getByLabel("当前 ETF")).toHaveValue("510500");
  await expect(page.getByRole("region", { name: "每日信号与执行记录" })).toBeVisible();
  await expect(page.getByRole("link", { name: "管理策略", exact: true })).toHaveAttribute("href", /page=strategies.*code=510500/);
});

test("绑定详情可按原始区间重新回测所用算法", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion]));
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await expect(page.getByRole("heading", { name: "算法绑定详情" })).toBeVisible();
  await page.getByRole("button", { name: "重新回测算法" }).click();
  await expect(page.getByLabel("开始日期")).toHaveValue(savedVersion.settings.start_date);
  await expect(page.getByLabel("结束日期")).toHaveValue(savedVersion.settings.end_date);
  await expect(page.getByRole("checkbox", { name: /箱体突破/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /底部确认/ })).not.toBeChecked();
});

test("绑定详情说明当前算法，不向用户展示算法或绑定版本号", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion]));
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await expect(page.getByRole("heading", { name: "算法绑定详情" })).toBeVisible();
  await expect(page.getByText(/绑定记录 \d+|模板 1\.0\.0|算法版本/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看当前算法说明" })).toBeVisible();
});

test("暂停信号保留算法绑定及原始回测", async ({ page }) => {
  let active = true;
  await page.route("**/api/strategies", (route) => json(route, [{ ...savedVersion, active }]));
  await page.route("**/api/strategies/10/pause", async (route) => {
    active = false;
    await json(route, { ...savedVersion, active });
  });
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await page.getByRole("button", { name: "暂停信号", exact: true }).click();
  await expect(page.getByText("箱体突破已暂停，历史信号仍可查看。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "启用每日信号", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "保存时的回测 · 只读快照" })).toBeVisible();
});
