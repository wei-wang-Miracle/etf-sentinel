import { test, expect } from "./fixtures";
for (const width of [1440, 1024, 768, 390]) {
  for (const theme of ["dark", "light"]) {
    test(`行情布局 ${width} ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(theme => localStorage.setItem("theme", theme), theme);
      await page.goto("/?page=etfs&code=510500&detail=overview&tab=price");
      const chart = page.getByRole("img", { name: /基金日K/ });
      await expect(chart).toBeVisible();
      const box = (await chart.boundingBox())!;
      if (width >= 1024) expect(box.y).toBeLessThanOrEqual(360);
      if (width === 390) { expect(box.width).toBeGreaterThanOrEqual(350); expect(box.y).toBeLessThanOrEqual(640); }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      await page.screenshot({ path: `/tmp/etf-redesign-${width}-${theme}.png`, fullPage: true });
    });
  }
}
for (const width of [1440, 390]) {
  for (const screen of ["strategies&code=510500&view=editor", "etfs&code=510500&detail=operations", "etfs&code=510500&detail=signals", "data&manage=account"]) {
    test(`主要工作区 ${width} ${screen}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      const errors: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      await page.goto(`/?page=${screen}`);
      await expect(page.locator("main h1")).toHaveCount(1);
      await expect(page.getByText(/正在读取|正在核验/)).toHaveCount(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      expect(errors).toEqual([]);
      await page.screenshot({ path: `/tmp/etf-redesign-${width}-${screen.split("&")[0]}-${screen.includes("operations") ? "operations" : "workspace"}.png`, fullPage: true });
    });
  }
}
test("200%文字与控件缩放后研究页面可重排", async ({ page }) => {
  await page.goto("/?page=etfs&code=510500&detail=overview");
  await expect(page.getByRole("img", { name: /基金日K/ })).toBeVisible();
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
  await expect(page.getByLabel("当前 ETF", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/etf-redesign-zoom200.png", fullPage: true });
});
