import type { TurningOptions } from "./turningPoints";

export const TURNING_GROUPS = {
  large: { name: "大盘宽基", index: "上证50／上证180／沪深300", codes: ["510050", "510180", "159919", "510300", "510310", "510330"] },
  mid: { name: "中盘宽基", index: "中证500", codes: ["159922", "510500", "512500"] },
  small: { name: "小盘宽基", index: "中证1000", codes: ["159629", "159845", "512100", "560010"] },
  micro: { name: "微盘宽基", index: "中证2000", codes: ["159531"] },
  growth: { name: "创业板成长", index: "创业板指", codes: ["159205", "159915", "159952", "159977"] },
  tech: { name: "科创科技", index: "科创50", codes: ["588050", "588080"] },
} as const;

export type TurningGroup = keyof typeof TURNING_GROUPS;

// 这三只ETF在本地研究区间内发生过份额折算；指标从折算后重新预热。
const ANALYSIS_START_AFTER_SPLIT: Record<string, string> = {
  "159922": "2024-12-02",
  "159977": "2025-09-15",
  "510310": "2024-09-23",
};

export const TURNING_OPTIONS_BY_GROUP: Record<TurningGroup, Partial<TurningOptions>> = {
  large: { backgroundDays: 1, slopeThreshold: 0.01, shortSlopeThreshold: 0, breakoutWindow: 5, breakoutAtrMultiplier: 0, confirmationDays: 2, cooldownDays: 0, confirmationMaWindow: 20, topConfirmationDays: 2, topMaWindow: 7, topBreakoutWindow: 5 },
  mid: { backgroundDays: 3, slopeThreshold: 0.01, shortSlopeThreshold: 0.3, breakoutWindow: 3, breakoutAtrMultiplier: 0.2, confirmationDays: 3, cooldownDays: 30, confirmationMaWindow: 20, topConfirmationDays: 1, topMaWindow: 3, topTrailingAtr: 3 },
  small: { backgroundDays: 5, slopeThreshold: 0.01, shortSlopeThreshold: 0.2, breakoutWindow: 3, breakoutAtrMultiplier: 0.2, confirmationDays: 3, cooldownDays: 0, confirmationMaWindow: 5, topConfirmationDays: 1, topMaWindow: 3, topTrailingAtr: 3 },
  micro: { backgroundDays: 3, slopeThreshold: 0.01, shortSlopeThreshold: 0, breakoutWindow: 3, breakoutAtrMultiplier: 0.4, confirmationDays: 2, cooldownDays: 30, confirmationMaWindow: 5, topConfirmationDays: 2, topMaWindow: 5 },
  growth: { backgroundDays: 3, slopeThreshold: 0.01, shortSlopeThreshold: 0.1, breakoutWindow: 2, breakoutAtrMultiplier: 0, confirmationDays: 2, cooldownDays: 10, confirmationMaWindow: 20, topConfirmationDays: 1, topMaWindow: 3 },
  tech: { backgroundDays: 5, slopeThreshold: 0.2, shortSlopeThreshold: 0.05, breakoutWindow: 5, breakoutAtrMultiplier: 0.2, confirmationDays: 2, cooldownDays: 30, confirmationMaWindow: 3, topConfirmationDays: 1, topMaWindow: 7 },
};

const groupByCode = Object.fromEntries(Object.entries(TURNING_GROUPS).flatMap(([group, value]) => value.codes.map(code => [code, group]))) as Record<string, TurningGroup>;

export function turningProfile(code: string) {
  const group = groupByCode[code] ?? "large";
  return { group, ...TURNING_GROUPS[group], analysisStart: ANALYSIS_START_AFTER_SPLIT[code], options: TURNING_OPTIONS_BY_GROUP[group] };
}
