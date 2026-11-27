import { test, expect, instruments, candles, factorCatalog, job, json, summary } from "./fixtures";

test("只输入代码新增 ETF，并从采集记录进入该标的日 K 查看因子", async ({ page }) => {
  const code = "510502";
  let added = false;
  let collected = false;
  const newEtf = { ...instruments[0], code, name: "测试新增 ETF" };
  const lastCandle = candles.at(-1)!;
  await page.clock.setFixedTime(new Date(`${lastCandle.date}T16:00:00Z`));
  await page.route("**/api/instruments", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ code });
      added = true;
      return json(route, { code, run_id: 42 }, 201);
    }
    return json(route, added ? [...instruments, {
      ...newEtf, count: collected ? newEtf.count : 0,
      first_date: collected ? newEtf.first_date : null,
      last_date: collected ? lastCandle.date : null,
    }] : instruments);
  });
  await page.route("**/api/job", (route) => json(route, {
    ...job, runs: [{ id: 42, status: "success", trigger: "manual", started_at: "2026-11-01T00:00:00Z",
      ended_at: "2026-11-01T00:01:00Z", logs: [{ kind: "equity", code, status: "success", message: "已核验权益" }] }],
  }));
  await page.route("**/api/research/object?**", (route) => {
    expect(new URL(route.request().url()).searchParams.get("code")).toBe(code);
    const item = summary(code);
    return json(route, { ...item, object: { ...item.object, name: newEtf.name } });
  });
  await page.route(`**/api/candles/${code}?**`, (route) => json(route, collected ? candles : []));
  await page.route(`**/api/candles/${code}/factors?**`, (route) => json(route, {
    events: [{ ...factorCatalog.factors[0], factor_id: "turning_bottom", trade_date: lastCandle.date }],
    data_cutoff: lastCandle.date, partial: false, warmup_insufficient: false,
  }));

  await page.goto("/?page=data&manage=instruments");
  await page.getByLabel("ETF 代码", { exact: true }).fill(code);
  await page.getByRole("button", { name: "新增 ETF", exact: true }).click();
  await expect(page.getByText(`${code} 已新增，已启动采集与核验`)).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: code });
  await expect(row.getByText("尚未采集")).toBeVisible();
  await page.getByRole("link", { name: "查看采集记录" }).click();
  await expect(page.getByRole("tab", { name: "基金日行情" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "查看日志", exact: true }).click();
  await expect(page.getByText("已核验权益")).toBeVisible();
  collected = true;
  await page.getByRole("link", { name: /返回原任务/ }).click();
  await row.getByRole("link", { name: "查看因子" }).click();
  await expect(page.getByRole("heading", { name: newEtf.name })).toBeVisible();
  await expect(page.getByText(`因子标记 · 本地日行情及已核验权益 · 数据截止 ${lastCandle.date}`)).toBeVisible();
});

test("新增失败保留输入并显示原因", async ({ page }) => {
  await page.route("**/api/instruments", (route) => route.request().method() === "POST"
    ? json(route, { detail: "该 ETF 已在标的配置中" }, 409) : json(route, instruments));
  await page.goto("/?page=data&manage=instruments");
  const input = page.getByLabel("ETF 代码", { exact: true });
  await input.fill("510500");
  await input.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("该 ETF 已在标的配置中");
  await expect(input).toHaveValue("510500");
});
