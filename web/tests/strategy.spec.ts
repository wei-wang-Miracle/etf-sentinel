import { test, expect, savedVersion, comparison, json } from "./fixtures";

test("没有对象时不默选 ETF", async ({ page }) => {
  await page.goto("/?page=strategies");
  await expect(page.getByText("先选择一只 ETF", { exact: true })).toBeVisible();
  await expect(page.getByLabel("当前 ETF")).toHaveValue("");
});

test("配置下一步只进入比较设置，结果修改后失效", async ({ page }) => {
  let calculations = 0;
  await page.route("**/api/strategies/comparisons", async (route) => {
    if (route.request().method() === "POST") calculations++;
    await route.fallback();
  });
  await page.goto("/?page=strategies&code=510500&view=editor");
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await page.getByRole("button", { name: "下一步：回测比较" }).click();
  expect(calculations).toBe(0);
  await expect(page).toHaveURL(/stage=compare/);
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toBeVisible();
  await page.getByLabel("初始研究资金（元）").fill("60000");
  await expect(page.getByText(/结果对应上次配置/)).toBeVisible();
  await expect(page.getByRole("button", { name: "继续：保存" })).toBeDisabled();
});

test("保存版本默认只读，修改需要明确进入新版", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion]));
  await page.goto("/?page=strategies&code=510500");
  await expect(page.getByText(/未启用/).first()).toBeVisible();
  await page.getByRole("button", { name: "查看版本" }).click();
  await expect(page.getByText("已保存版本 · 只读")).toBeVisible();
  await expect(page.getByRole("button", { name: "基于此版本修改" })).toBeVisible();
});

test("策略与信号入口打开当前 ETF 的完整信号页并可返回", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500");
  await page.getByRole("button", { name: "查看策略与信号", exact: true }).click();
  await expect(page).toHaveURL(/page=etfs/);
  await expect(page).toHaveURL(/detail=signals/);
  await expect(page.getByLabel("当前 ETF")).toHaveValue("510500");
  await expect(page.getByRole("region", { name: "每日信号与执行记录" })).toBeVisible();
  await expect(page.getByRole("link", { name: "管理策略", exact: true })).toHaveAttribute("href", /page=strategies.*code=510500/);
  await page.goBack();
  await expect(page.getByRole("heading", { name: "已保存的方法" })).toBeVisible();
});

test("已有版本直接查看冻结回测，再比较而无需创建或保存策略", async ({ page }) => {
  const version = { ...savedVersion, comparison_id: comparison.id };
  const snapshot = { ...comparison, tracks: comparison.tracks.map((row) => ({ ...row, backtest_id: savedVersion.backtest_id })) };
  let saves = 0, draftWrites = 0;
  let submitted: Record<string, unknown> = {};
  await page.route("**/api/strategies**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path === "/api/strategies") {
      if (method === "POST") saves++;
      return json(route, [version]);
    }
    if (path.includes("/drafts/") && method === "PUT") draftWrites++;
    if (path === "/api/strategies/comparisons/5") return json(route, snapshot);
    if (path === "/api/strategies/comparisons" && method === "POST") {
      submitted = route.request().postDataJSON();
      return json(route, comparison);
    }
    await route.fallback();
  });
  await page.goto("/?page=strategies&code=510500");
  await page.getByRole("button", { name: "查看版本", exact: true }).click();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "保存时的回测 · 只读快照", exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toBeVisible();
  await page.getByRole("button", { name: "回测与比较此版本", exact: true }).click();
  await expect(page.getByRole("heading", { name: "回测并比较", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "策略名称", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("开始日期")).toHaveValue(savedVersion.settings.start_date);
  await page.getByLabel("初始研究资金（元）").fill("60000");
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toBeVisible();
  expect(submitted.version_ids).toEqual([savedVersion.id]);
  expect(submitted.current).toBeUndefined();
  expect(submitted.initial_cash).toBe("60000");
  await expect(page.getByRole("button", { name: "继续：保存" })).toHaveCount(0);
  await expect(page.getByText(/草稿已保存/)).toHaveCount(0);
  await page.getByRole("button", { name: "返回版本详情", exact: true }).click();
  await expect(page.getByText("已保存版本 · 只读")).toBeVisible();
  expect(saves).toBe(0);
  expect(draftWrites).toBe(0);
});

test("冻结回测读取失败可重试，仍可继续比较并默认选中本版本", async ({ page }) => {
  const version = { ...savedVersion, comparison_id: comparison.id };
  const other = { ...comparison.tracks[0], key: "other", name: "另一条方法", backtest_id: 99 };
  const chosen = { ...comparison.tracks[0], key: "chosen", name: savedVersion.name, backtest_id: savedVersion.backtest_id };
  let available = false;
  await page.route("**/api/strategies", (route) => json(route, [version]));
  await page.route("**/api/strategies/comparisons/5", (route) => {
    return json(route, available ? { ...comparison, tracks: [other, chosen] } : { detail: "测试快照暂时不可用" }, available ? 200 : 503);
  });
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await expect(page.getByRole("alert")).toContainText("测试快照暂时不可用");
  await expect(page.getByRole("button", { name: "回测与比较此版本" })).toBeEnabled();
  available = true;
  await page.getByRole("button", { name: "重试回测" }).click();
  await expect(page.getByRole("button", { name: "查看买卖点" }).nth(1)).toHaveAttribute("aria-pressed", "true");
});

test("版本快照缺失不阻断比较，比较不恢复或覆盖编辑草稿", async ({ page }) => {
  for (const path of ["**/api/strategies", "**/api/strategies?*"]) {
    await page.route(path, (route) => json(route, [savedVersion]));
  }
  const draft = { name: "保留的编辑草稿", rule: savedVersion.rule, settings: { ...savedVersion.settings, initial_cash: "88000" } };
  await page.addInitScript((value) => localStorage.setItem("etf-strategy-draft:510500:10", JSON.stringify(value)), draft);
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await expect(page.getByText(/此版本暂无关联的比较快照/)).toBeVisible();
  await page.getByRole("button", { name: "回测与比较此版本" }).click();
  await expect(page.getByLabel("初始研究资金（元）")).toHaveValue(savedVersion.settings.initial_cash);
  await page.getByLabel("初始研究资金（元）").fill("60000");
  await page.getByRole("checkbox", { name: /测试趋势/ }).uncheck();
  await expect(page.getByRole("button", { name: "运行回测", exact: true })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole("heading", { name: "回测并比较", exact: true })).toBeVisible();
  expect(JSON.parse((await page.evaluate(() => localStorage.getItem("etf-strategy-draft:510500:10")))!)).toEqual(draft);
});

test("比较入口拒绝跨 ETF 版本，版本快照也不展示不匹配结果", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [{ ...savedVersion, comparison_id: comparison.id }]));
  await page.route("**/api/strategies/comparisons/5", (route) => json(route, { ...comparison, instrument_code: "512100" }));
  await page.goto("/?page=strategies&code=512100&view=compare&edit=10");
  await expect(page.getByText("策略版本不存在或已不属于当前ETF，请重新选择。")).toBeVisible();
  await expect(page.getByRole("button", { name: "运行回测", exact: true })).toHaveCount(0);
  await page.goto("/?page=strategies&code=510500&view=version&edit=10");
  await expect(page.getByText(/回测快照与当前版本不匹配/)).toBeVisible();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toHaveCount(0);
});

test("保存成功启用失败时只重试同一版本", async ({ page }) => {
  let saves = 0, enables = 0;
  await page.route("**/api/strategies", async (route) => {
    if (route.request().method() === "POST") { saves++; await json(route, savedVersion); }
    else await json(route, []);
  });
  await page.route("**/api/strategies/10/enable", async (route) => {
    enables++;
    await json(route, enables === 1 ? { detail: "测试依赖尚未就绪" } : { ...savedVersion, active: true }, enables === 1 ? 409 : 200);
  });
  await page.goto("/?page=strategies&code=510500&view=editor");
  await page.getByRole("button", { name: "下一步：回测比较" }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await page.getByRole("button", { name: "继续：保存" }).click();
  await page.getByRole("button", { name: "保存并启用…" }).click();
  await page.getByRole("button", { name: "确认启用", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("版本已保存，启用未成功");
  await page.getByRole("button", { name: "确认启用", exact: true }).click();
  await expect(page.getByRole("status").first()).toContainText("策略已启用");
  expect(saves).toBe(1);
  expect(enables).toBe(2);
});

test("聚焦字段不自动打开说明，主动查看说明不推移条件", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500&view=editor");
  const window = page.getByLabel("回看交易日").first();
  const before = await window.boundingBox();
  await window.focus();
  await expect(window).toBeFocused();
  expect((await window.boundingBox())?.y).toBe(before?.y);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await window.focus();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  const help = page.getByRole("button", { name: "指标说明", exact: true });
  await help.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(help).toBeFocused();
});


test("历史比较只读且返回后保留当前草稿", async ({ page }) => {
  const snapshot = { ...comparison, settings: { ...comparison.settings, initial_cash: "72000" }, tracks: comparison.tracks.map((row) => ({ ...row, rule: { ...savedVersion.rule, allocation: 50 } })) };
  await page.route("**/api/strategies/comparisons?*", (route) => json(route, [snapshot]));
  await page.route("**/api/strategies/comparisons/5", (route) => json(route, snapshot));
  await page.goto("/?page=strategies&code=510500&view=editor");
  await page.getByLabel("策略名称").fill("保留我的草稿");
  await page.getByText("这只 ETF 的比较记录（1）").click();
  await page.getByRole("button", { name: "比较 #5" }).click();
  await expect(page.getByRole("heading", { name: "历史比较 · 只读快照" })).toBeVisible();
  await expect(page.getByText(/研究本金 72,000/).first()).toBeVisible();
  await expect(page.getByText(/使用一半资金/)).toBeVisible();
  await expect(page.getByRole("button", { name: "运行回测", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "返回当前草稿" }).click();
  await expect(page.getByLabel("策略名称")).toHaveValue("保留我的草稿");
});

test("启用成功后刷新失败仍保留成功并收起启用操作", async ({ page }) => {
  let enabled = false;
  await page.route("**/api/strategies**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/strategies/10/enable") { enabled = true; return json(route, { ...savedVersion, active: true }); }
    if (path === "/api/strategies") {
      if (route.request().method() === "POST") return json(route, savedVersion);
      return json(route, enabled ? { detail: "测试版本列表刷新失败" } : [], enabled ? 503 : 200);
    }
    await route.fallback();
  });
  await page.goto("/?page=strategies&code=510500&view=editor");
  await page.getByRole("button", { name: "下一步：回测比较" }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await page.getByRole("button", { name: "继续：保存" }).click();
  await page.getByRole("button", { name: "保存并启用…" }).click();
  await page.getByRole("button", { name: "确认启用", exact: true }).click();
  await expect(page.getByText(/版本列表刷新失败，已保存或启用的结果不受影响/)).toBeVisible();
  await expect(page.getByText(/版本已保存，启用未成功/)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看每日信号" })).toHaveClass(/primary/);
  await expect(page.getByRole("button", { name: "启用已保存版本…" })).toHaveCount(0);
});

test("只读版本拒绝跨 ETF 的版本链接", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion]));
  await page.goto("/?page=strategies&code=512100&view=version&edit=10");
  await expect(page.getByText("策略版本不存在或已不属于当前ETF，请重新选择。")).toBeVisible();
  await expect(page.getByRole("button", { name: "基于此版本修改" })).toHaveCount(0);
});

test("新策略沿用研究区间并提交相同回测日期", async ({ page }) => {
  let submitted: { start_date?: string; end_date?: string } = {};
  await page.route("**/api/strategies/comparisons", async (route) => {
    if (route.request().method() === "POST") submitted = route.request().postDataJSON();
    await route.fallback();
  });
  await page.goto("/?page=strategies&code=510500&view=editor&start=2026-02-03&end=2026-09-25");
  await page.getByRole("button", { name: "下一步：回测比较" }).click();
  await expect(page.getByLabel("开始日期")).toHaveValue("2026-02-03");
  await expect(page.getByLabel("截止日期")).toHaveValue("2026-09-25");
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("table", { name: "策略指标对照" })).toBeVisible();
  expect(submitted.start_date).toBe("2026-02-03");
  expect(submitted.end_date).toBe("2026-09-25");
});

test("未选 ETF 时展示完整流程指引与信号边界", async ({ page }) => {
  await page.goto("/?page=strategies");
  const guide = page.getByRole("region", { name: "策略流程指引" });
  await expect(guide).toBeVisible();
  for (const step of ["选择 ETF", "配置买卖条件", "回测验证", "保存命名版本", "启用每日信号"]) {
    await expect(guide.getByText(step, { exact: true })).toBeVisible();
  }
  await expect(guide.getByText(/信号不等于成交/)).toBeVisible();
  await expect(guide.getByText(/不自动下单/)).toBeVisible();
});

test("没有保存策略时提示先创建并先回测再保存", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500");
  await expect(page.getByText(/创建第一个策略/)).toBeVisible();
  await expect(page.getByText(/先回测，满意再保存/)).toBeVisible();
});

test("有保存未启用版本时提示启用后才产生每日信号", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [savedVersion]));
  await page.goto("/?page=strategies&code=510500");
  await expect(page.getByText(/启用一个版本，系统才会在每个交易日盘前生成信号/)).toBeVisible();
});

test("已有启用版本时不再显示下一步引导，直接展示信号摘要", async ({ page }) => {
  await page.route("**/api/strategies", (route) => json(route, [{ ...savedVersion, active: true }]));
  await page.goto("/?page=strategies&code=510500");
  await expect(page.getByText(/创建第一个策略/)).toHaveCount(0);
  await expect(page.getByText(/启用一个版本，系统才会/)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "每日信号摘要" })).toBeVisible();
});

test("旧实验入口已移除，历史链接兼容落到策略列表", async ({ page }) => {
  await page.goto("/?page=strategies&code=510500");
  await expect(page.getByRole("link", { name: /历史实验记录/ })).toHaveCount(0);
  await page.goto("/?page=backtests");
  await expect(page).toHaveURL(/page=strategies/);
  await expect(page.getByRole("button", { name: "单次回测与历史实验" })).toHaveCount(0);
});

test("已有草稿优先保留日期并说明与研究链接不同", async ({ page }) => {
  await page.route("**/api/strategies/drafts/510500", (route) => json(route, { name: "已有草稿", rule: savedVersion.rule, settings: savedVersion.settings }));
  await page.goto("/?page=strategies&code=510500&view=editor&start=2026-02-03&end=2026-09-25");
  await expect(page.getByText(/已保留草稿或版本的日期/)).toBeVisible();
  await page.getByRole("button", { name: "下一步：回测比较" }).click();
  await expect(page.getByLabel("开始日期")).toHaveValue(savedVersion.settings.start_date);
  await expect(page.getByLabel("截止日期")).toHaveValue(savedVersion.settings.end_date);
});
