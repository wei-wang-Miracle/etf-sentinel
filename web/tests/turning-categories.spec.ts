import { test, expect } from "@playwright/test";
import { TURNING_GROUPS, turningProfile } from "../src/lib/turningCategories";

test("20只配置ETF恰好归入一个跟踪指数类别", () => {
  const codes = Object.values(TURNING_GROUPS).flatMap(group => group.codes);
  expect(codes).toHaveLength(20);
  expect(new Set(codes).size).toBe(20);
  for (const code of codes) {
    const profile = turningProfile(code);
    expect(profile.codes).toContain(code);
    expect(profile.index).not.toBe("");
  }
});

test("不同类别返回对应的独立实验参数", () => {
  expect(turningProfile("510500").name).toBe("中盘宽基");
  expect(turningProfile("512100").name).toBe("小盘宽基");
  expect(turningProfile("588050").name).toBe("科创科技");
  expect(turningProfile("510500").options.topTrailingAtr).toBe(3);
  expect(turningProfile("510300").options.topTrailingAtr).toBeUndefined();
  expect(turningProfile("159922").analysisStart).toBe("2024-12-02");
  expect(turningProfile("159977").analysisStart).toBe("2025-09-15");
  expect(turningProfile("510310").analysisStart).toBe("2024-09-23");
});
