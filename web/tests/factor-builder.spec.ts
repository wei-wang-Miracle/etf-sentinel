import { test, expect, catalog, json, rule, settings } from "./fixtures";

const editorUrl = "/?page=strategies&code=510500&view=editor";

test("拖拽因子复制到目标组，库中指标保留，落在组外不修改", async ({ page }) => {
  await page.goto(editorUrl);
  const library = page.getByRole("region", { name: "全部指标", exact: true });
  const source = library.getByRole("listitem").filter({ hasText: "含分红走势动量" });
  const buy = page.getByRole("group", { name: "什么时候买", exact: true });
  const sell = page.getByRole("group", { name: "什么时候卖", exact: true });
  await source.dragTo(buy);
  await expect(buy.getByRole("article")).toHaveCount(2);
  await expect(sell.getByRole("article")).toHaveCount(1);
  await expect(buy.getByRole("article", { name: "买入条件2", exact: true })).toContainText("含分红走势动量");
  await expect(source).toBeVisible();
  await source.dragTo(page.getByRole("heading", { name: "创建策略", exact: true }));
  await expect(buy.getByRole("article")).toHaveCount(2);
  await source.dragTo(sell);
  await expect(sell.getByRole("article")).toHaveCount(2);
  await expect(sell.getByRole("article", { name: "卖出条件2", exact: true }).getByLabel("比较")).toHaveValue("gt");
});

test("键盘添加与参数修改保存草稿，回测提交原有规则结构", async ({ page }) => {
  let submitted: { current: { rule: typeof rule } } | undefined;
  await page.route("**/api/strategies/comparisons", async (route) => {
    if (route.request().method() === "POST") submitted = route.request().postDataJSON();
    await route.fallback();
  });
  await page.goto(editorUrl);
  const add = page.getByRole("button", { name: "将含分红走势动量加入买入条件", exact: true });
  await add.focus();
  await page.keyboard.press("Enter");
  const buy = page.getByRole("group", { name: "什么时候买", exact: true });
  const second = buy.getByRole("article", { name: "买入条件2", exact: true });
  await second.getByLabel("回看交易日").fill("30");
  await second.getByLabel("阈值（%）", { exact: true }).fill("5");
  await buy.getByLabel("触发方式").selectOption("any");
  await page.getByLabel("参与交易的比例").selectOption("50");
  await expect(page.getByText("本机与服务端草稿已保存")).toBeVisible();
  await page.reload();
  await expect(second.getByLabel("回看交易日")).toHaveValue("30");
  await expect(buy.getByLabel("触发方式")).toHaveValue("any");
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect.poll(() => submitted?.current.rule.buy.conditions.length).toBe(2);
  expect(submitted!.current.rule).toEqual({ ...rule, allocation: 50, buy: { mode: "any", conditions: [rule.buy.conditions[0], { indicator: "momentum", window: 30, operator: "gt", threshold: "5" }] } });
});

test("每组至少一条至多二十条，满组阻止添加与拖入，删除后恢复", async ({ page }) => {
  await page.route("**/api/strategies/drafts/510500", (route) => json(route, {
    name: "条件上限测试", settings, rule: { ...rule, buy: { mode: "all", conditions: Array.from({ length: 20 }, () => rule.buy.conditions[0]) } },
  }));
  await page.goto(editorUrl);
  const buy = page.getByRole("group", { name: "什么时候买", exact: true });
  const sell = page.getByRole("group", { name: "什么时候卖", exact: true });
  const add = page.getByRole("button", { name: "将含分红走势动量加入买入条件", exact: true });
  await expect(add).toBeDisabled();
  await expect(sell.getByRole("button", { name: "删除卖出条件1", exact: true })).toBeDisabled();
  const source = page.getByRole("region", { name: "全部指标", exact: true }).getByRole("listitem").filter({ hasText: "含分红走势动量" });
  await source.dragTo(buy);
  await expect(buy.getByRole("article")).toHaveCount(20);
  await buy.getByRole("button", { name: "删除买入条件1", exact: true }).click();
  await expect(add).toBeEnabled();
  await add.click();
  await expect(buy.getByRole("article")).toHaveCount(20);
  await expect(buy.getByRole("article", { name: "买入条件20", exact: true })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole("button", { name: "下一步：回测比较", exact: true })).toBeInViewport({ ratio: 1 });
});

test("拖入因子改变规则后，旧比较失效且不能直接保存", async ({ page }) => {
  await page.goto(editorUrl);
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect(page.getByRole("button", { name: "继续：保存", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "返回修改规则", exact: true }).click();
  const source = page.getByRole("region", { name: "全部指标", exact: true }).getByRole("listitem").filter({ hasText: "含分红走势动量" });
  await source.dragTo(page.getByRole("group", { name: "什么时候买", exact: true }));
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await expect(page.getByText(/结果对应上次配置/)).toBeVisible();
  await expect(page.getByRole("button", { name: "继续：保存", exact: true })).toBeDisabled();
});

test("缺数据指标可阅读说明，恐贪要求选择类别，弹层关闭后返回焦点", async ({ page }) => {
  await page.route("**/api/strategies/coverage?*", (route) => json(route, { conditions: [{ key: "sentiment", status: "unavailable", reason: "尚未采集恐贪数据" }] }));
  await page.goto(editorUrl);
  const source = page.getByRole("region", { name: "全部指标", exact: true }).getByRole("listitem").filter({ hasText: "指定类别恐贪分数" });
  await expect(source).toContainText("暂不可用");
  const help = page.getByRole("region", { name: "全部指标", exact: true }).getByRole("button", { name: "指标说明", exact: true });
  await help.click();
  const dialog = page.getByRole("dialog", { name: "指标说明", exact: true });
  await dialog.getByLabel("查看指标").selectOption("sentiment");
  await expect(dialog).toContainText("投资含义");
  await expect(dialog).toContainText("尚未采集恐贪数据");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(help).toBeFocused();
  await source.getByRole("button", { name: "将指定类别恐贪分数加入买入条件", exact: true }).click();
  const condition = page.getByRole("article", { name: "买入条件2", exact: true });
  await expect(condition).toContainText("暂不可用");
  await expect(condition).not.toContainText("尚未采集恐贪数据");
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await expect(page).not.toHaveURL(/stage=compare/);
  await condition.getByLabel("市场背景类别").selectOption("wide");
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await expect(page).toHaveURL(/stage=compare/);
});

test("说明只保留左栏统一入口，四条条件的参数同屏完整可见", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  const conditions = [
    { indicator: "pe_percentile", operator: "lt", threshold: "10" },
    { indicator: "sentiment", operator: "lt", threshold: "10", category_key: "wide" },
    { indicator: "volatility", operator: "lt", threshold: "10", window: 10 },
    { indicator: "momentum", operator: "gt", threshold: "5", window: 20 },
  ];
  await page.route("**/api/strategies/drafts/510500", (route) => json(route, {
    name: "紧凑配置测试", settings, rule: { buy: { mode: "all", conditions }, sell: { mode: "any", conditions }, allocation: 100 },
  }));
  await page.goto(editorUrl);
  await expect(page.getByRole("button", { name: "指标说明", exact: true })).toHaveCount(1);
  for (const name of ["什么时候买", "什么时候卖"]) {
    const group = page.getByRole("group", { name, exact: true });
    await expect(group.getByRole("button", { name: /说明/ })).toHaveCount(0);
    await expect(group.getByText(/可用于历史回测|修订历史研究|2024-01-02/)).toHaveCount(0);
    for (const input of await group.locator("input, select").all()) await expect(input).toBeInViewport({ ratio: 1 });
    await expect(group.getByLabel("阈值（%）").last()).toHaveCSS("height", "28px");
  }
  await expect(page.getByRole("button", { name: "下一步：回测比较", exact: true })).toBeInViewport({ ratio: 1 });
  await page.screenshot({ path: "/tmp/etf-factor-builder-dense.png", fullPage: true });
});

test("全部指标缺数据时左栏仍完整可见，原因集中在说明中", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.route("**/api/strategies/coverage?*", (route) => json(route, { conditions: catalog.conditions.map((item) => ({ key: item.key, status: "unavailable", reason: "尚未取得对应数据" })) }));
  await page.goto(editorUrl);
  const library = page.getByRole("region", { name: "全部指标", exact: true });
  await expect(library.getByRole("listitem")).toHaveCount(catalog.conditions.length);
  for (const item of await library.getByRole("listitem").all()) {
    await item.scrollIntoViewIfNeeded();
    await expect(item).toBeInViewport({ ratio: 1 });
  }
  const libraryBox = (await library.boundingBox())!;
  const last = (await library.getByRole("listitem").last().boundingBox())!;
  expect(last.y + last.height).toBeLessThanOrEqual(libraryBox.y + libraryBox.height);
});

for (const [width, height] of [[1440, 900], [1366, 768]]) {
  for (const theme of ["dark", "light"]) {
    test(`一屏配置 ${width}×${height} ${theme}，分类指标可滚动访问且操作可见`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.addInitScript((value) => localStorage.setItem("theme", value), theme);
      await page.goto(editorUrl);
      const library = page.getByRole("region", { name: "全部指标", exact: true });
      for (const definition of catalog.conditions) {
        const item = library.getByText(definition.display_label ?? definition.label, { exact: true });
        await item.scrollIntoViewIfNeeded();
        await expect(item).toBeInViewport({ ratio: 1 });
      }
      for (const name of ["策略名称", "参与交易的比例"]) await expect(page.getByLabel(name)).toBeInViewport({ ratio: 1 });
      for (const name of ["什么时候买", "什么时候卖"]) await expect(page.getByRole("group", { name, exact: true })).toBeInViewport({ ratio: 1 });
      const libraryBox = (await library.boundingBox())!;
      const footerBox = (await page.locator(".factor-editor-footer").boundingBox())!;
      expect(libraryBox.y + libraryBox.height).toBeLessThanOrEqual(footerBox.y);
      await expect(page.getByRole("button", { name: "下一步：回测比较", exact: true })).toBeInViewport({ ratio: 1 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await page.screenshot({ path: `/tmp/etf-factor-builder-${width}-${theme}.png`, fullPage: true });
    });
  }
}

test("窄屏与放大可点击添加及编辑，无横向溢出和裁切", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(editorUrl);
  await page.getByRole("button", { name: "将含分红走势动量加入卖出条件", exact: true }).click();
  await expect(page.getByRole("article", { name: "卖出条件2", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: "/tmp/etf-factor-builder-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await page.getByRole("article", { name: "卖出条件2", exact: true }).getByLabel("阈值（%）", { exact: true }).fill("3");
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await expect(page).toHaveURL(/stage=compare/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
});


test("指标按来源分组，新因子支持双窗口与事件参数并保存提交", async ({ page }) => {
  let submitted: { current: { rule: { buy: { conditions: unknown[] } } } } | undefined;
  await page.route("**/api/strategies/comparisons", async (route) => {
    if (route.request().method() === "POST") submitted = route.request().postDataJSON();
    await route.fallback();
  });
  await page.goto(editorUrl);
  const library = page.getByRole("region", { name: "全部指标", exact: true });
  for (const name of ["ETF 日 K", "关联指数估值", "市场／行业恐贪", "国家队持仓估算"]) await expect(library.getByRole("region", { name, exact: true })).toBeVisible();
  await library.getByRole("button", { name: "将双均线交叉加入买入条件", exact: true }).click();
  const cross = page.getByRole("article", { name: "买入条件2", exact: true });
  await cross.getByLabel("短窗口交易日").fill("5");
  await cross.getByLabel("长窗口交易日").fill("10");
  await cross.getByRole("combobox", { name: "比较", exact: true }).selectOption("cross_down");
  await expect(cross.getByLabel(/阈值/)).toHaveCount(0);
  await expect(cross.getByLabel("比较").getByRole("option")).toHaveCount(2);
  await library.getByRole("button", { name: "将均线变化率加入买入条件", exact: true }).click();
  await page.getByRole("article", { name: "买入条件3", exact: true }).getByLabel("比较间隔交易日").fill("3");
  await library.getByRole("button", { name: "将日成交量相对均量加入买入条件", exact: true }).click();
  await expect(page.getByRole("article", { name: "买入条件4", exact: true }).getByLabel("阈值（倍）")).toHaveValue("1");
  await page.getByRole("button", { name: "下一步：回测比较", exact: true }).click();
  await page.getByRole("button", { name: "运行回测", exact: true }).click();
  await expect.poll(() => submitted?.current.rule.buy.conditions.length).toBe(4);
  expect(submitted!.current.rule.buy.conditions[1]).toEqual({ indicator: "ma_cross", window: 5, long_window: 10, operator: "cross_down", threshold: "0" });
  await page.getByText("当前草稿 · 条件触发诊断", { exact: true }).click();
  await expect(page.getByRole("table", { name: "买入条件满足统计" })).toContainText("均线乖离率");
  await expect(page.getByText(/实际模拟买入 0 次/)).toBeVisible();
});
