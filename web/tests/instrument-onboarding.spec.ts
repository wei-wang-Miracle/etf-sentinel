import { test, expect, instruments, candles, factorCatalog, job, json, summary } from "./fixtures";

test("先核验再新增 ETF，并从采集记录进入该标的日 K 查看因子", async ({ page }) => {
  const code = "510502";
  let added = false;
  let collected = false;
  const newEtf = { ...instruments[0], code, name: "测试新增 ETF" };
  const lastCandle = candles.at(-1)!;
  await page.clock.setFixedTime(new Date(`${lastCandle.date}T16:00:00Z`));
  await page.route("**/api/instruments", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({
        code,
        confirm_index_link: true,
        tracking_index_code: "000905.SH",
        mapping_evidence: "基金合同与指数代码核验",
      });
      added = true;
      return json(route, { code, run_id: 42 }, 201);
    }
    return json(route, added ? [...instruments, {
      ...newEtf, count: collected ? newEtf.count : 0,
      first_date: collected ? newEtf.first_date : null,
      last_date: collected ? lastCandle.date : null,
    }] : instruments);
  });
  await page.route(`**/api/instruments/preview/${code}`, (route) => json(route, {
    code, market_verified: true, market_name: newEtf.name, market_row_count: 20,
    already_configured: false,
    funddb_profile: {
      fund_name: newEtf.name, fund_full_name: newEtf.name, category_primary: "股票型ETF", category_tag: "中证500",
      tracking_index_code: "000905.SH", tracking_index_name: "中证500", index_corr: 0.97,
      setup_date: "2013-02-06", management_fee_pct: 0.5, custody_fee_pct: 0.1, linked_otc_code: null,
    }, suggested_index_exists: true, warnings: [],
  }));
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
  await page.getByRole("button", { name: "核验并预览", exact: true }).click();
  await expect(page.getByText(/已通过近30日行情核验/)).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "同时建立已核验指数关联" })).toBeChecked();
  await page.getByLabel("指数关联依据", { exact: true }).fill("基金合同与指数代码核验");
  await page.getByRole("button", { name: "确认新增 ETF", exact: true }).click();
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

test("行情核验失败保留输入并显示原因", async ({ page }) => {
  await page.route("**/api/instruments/preview/510500", (route) => json(route, { detail: "数据源近30日未返回该代码的ETF行情" }, 422));
  await page.goto("/?page=data&manage=instruments");
  const input = page.getByLabel("ETF 代码", { exact: true });
  await input.fill("510500");
  await input.press("Enter");
  await expect(page.getByRole("alert")).toHaveText("数据源近30日未返回该代码的ETF行情");
  await expect(input).toHaveValue("510500");
});
