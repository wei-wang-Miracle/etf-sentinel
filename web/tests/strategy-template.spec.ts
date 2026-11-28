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

test("比较观察类策略展示对比数据但不开放采用按钮", async ({ page }) => {
  const observationCatalog = {
    ...catalog,
    strategies: [
      ...catalog.strategies,
      {
        id: "trend_pullback",
        name: "趋势回踩",
        description: "观察用因子策略",
        adoptable: false,
        supported_instruments: ["510500"],
        factors: [],
      },
    ],
  };
  const observationResult = {
    ...result,
    complete: true,
    tracks: [
      result.tracks[0],
      { ...track, key: "strategy:trend_pullback", strategy_id: "trend_pullback", name: "趋势回踩", status: "success" },
      result.tracks[2],
    ],
  };
  await page.route("**/api/strategies/catalog", (route) => json(route, observationCatalog));
  await page.route("**/api/strategies/comparisons", (route) => json(route, observationResult));
  await page.goto("/?page=strategies&code=510500&view=backtest");
  await expect(page.getByText("趋势回踩（仅比较观察）")).toBeVisible();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  const table = page.getByRole("table", { name: "算法指标对照" });
  await expect(table.getByRole("button", { name: "采用箱体突破" })).toBeVisible();
  await expect(table.getByRole("button", { name: "采用趋势回踩" })).toHaveCount(0);
  await expect(table.getByText("仅比较观察", { exact: true })).toBeVisible();
});

test("按分类过滤适用策略，并在250日预热不足时自动避开与提供一键调晚按钮", async ({ page }) => {
  const scopedCatalog = {
    ...catalog,
    instruments: [
      { ...catalog.instruments[0], research_category: "黄金" },
      { ...catalog.instruments[0], instrument_code: "159915", instrument_name: "创业板ETF", research_category: "创业板" },
    ],
    strategies: [
      ...catalog.strategies.map((item) => ({
        ...item,
        scope_type: "universal" as const,
        adoptable_instruments: ["510500", "159915"],
        supported_instruments: ["510500", "159915"],
        min_warmup_bars: 60,
        earliest_start_by_instrument: { "510500": "2024-06-01", "159915": "2024-06-01" },
      })),
      {
        id: "trend_pullback",
        name: "趋势回踩",
        description: "黄金分类长均线趋势回踩策略",
        scope_type: "category" as const,
        bound_categories: ["黄金"],
        adoptable: true,
        adoptable_instruments: ["510500"],
        supported_instruments: ["510500"],
        min_warmup_bars: 250,
        earliest_start_by_instrument: { "510500": "2025-06-02" },
        factors: [],
      },
      {
        id: "gem_bottom_contraction",
        name: "创业板底分型缩波",
        description: "创业板专用观察策略",
        scope_type: "category" as const,
        bound_categories: ["创业板"],
        adoptable: false,
        adoptable_instruments: [],
        supported_instruments: ["159915"],
        min_warmup_bars: 66,
        earliest_start_by_instrument: { "159915": "2024-07-01" },
        factors: [],
      },
    ],
  };
  let submitted: { strategies: string[]; start_date: string } | undefined;
  await page.route("**/api/strategies/catalog", (route) => json(route, scopedCatalog));
  await page.route("**/api/strategies/comparisons", async (route) => {
    submitted = route.request().postDataJSON();
    return json(route, comparison);
  });

  await page.goto("/?page=strategies&code=510500&view=backtest");
  await expect(page.getByText("创业板底分型缩波")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /调至 2025-06-02 以启用全部/ })).toBeVisible();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  expect(submitted?.strategies).not.toContain("trend_pullback");

  await page.getByRole("button", { name: /调至 2025-06-02 以启用全部/ }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  expect(submitted?.start_date).toBe("2025-06-02");
  expect(submitted?.strategies).toContain("trend_pullback");
});

test("空策略库展示清空说明并禁用开始对比与运行回测", async ({ page }) => {
  await page.route("**/api/strategies/catalog", (route) =>
    json(route, { ...catalog, strategies: [], assignments: [] }),
  );
  await page.goto("/?page=strategies");
  await expect(page.getByText(/当前策略库已清空/)).toBeVisible();
  await expect(page.getByRole("button", { name: "开始策略对比" })).toBeDisabled();

  await page.goto("/?page=strategies&code=510500&view=backtest");
  await expect(page.getByText(/当前策略库已清空，暂无可参加比较的策略/)).toBeVisible();
  await expect(page.getByRole("button", { name: "运行回测" })).toBeDisabled();
});
