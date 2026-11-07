import type { Account } from "./backtests";
import type { Diagnostics } from "./strategyLab";
import type { AccountHoldings } from "./account";
import { stamp } from "./api";

export type Condition = {
  indicator: string;
  window?: number;
  operator: "gt" | "gte" | "lt" | "lte";
  threshold: string;
  category_key?: string;
};
export type ConditionGroup = { mode: "all" | "any"; conditions: Condition[] };
export type Rule = { buy: ConditionGroup; sell: ConditionGroup; allocation: 50 | 100 };
export type ResearchSettings = {
  instrument_code: string;
  start_date: string;
  end_date: string;
  initial_cash: string;
  commission_rate: string;
  minimum_commission: string;
  slippage_bps: string;
};
export type SavedStrategy = {
  id: number;
  strategy_id: number;
  name: string;
  version: number;
  instrument_code: string;
  rule: Rule;
  settings: ResearchSettings;
  backtest_id: number;
  active: boolean;
  observation_id: number | null;
  created_at: string;
  readiness?: { status: string; target?: number; reason?: string; data_cutoff?: string };
  next_run?: string | null;
};
export type ConditionDefinition = {
  key: string;
  label: string;
  unit: string;
  window: boolean;
  description: string;
  evidence_type: string;
};
export type JourneyCatalog = {
  instruments: {
    instrument_code: string;
    instrument_name: string;
    first_date: string | null;
    last_date: string | null;
    default_start: string | null;
    source_checked_through: string | null;
  }[];
  conditions: ConditionDefinition[];
  sentiment_categories: { key: string; name: string }[];
};
export type Coverage = {
  conditions: { key: string; status: string; reason?: string; first_date?: string | null; last_date?: string | null }[];
};
export type ComparisonTrack = {
  key: string;
  name: string;
  version_id?: number | null;
  status: string;
  reason?: string;
  backtest_id?: number;
  account?: Account;
  diagnostics?: Diagnostics;
  evidence_type: string;
};
export type Comparison = {
  id: number;
  instrument_code: string;
  created_at: string;
  settings: ResearchSettings;
  input_sha256: string;
  tracks: ComparisonTrack[];
  complete: boolean;
  market_rows: { trade_date: string; open: string; high: string; low: string; close: string; volume: string; source_updated_at: string | null; collected_at: string }[];
};
export type Draft = { name: string; rule: Rule; settings: ResearchSettings; strategy_id?: number };

export const operatorNames = { gt: "高于", gte: "不低于", lt: "低于", lte: "不高于" };
export const trendRule = (): Rule => ({
  buy: { mode: "all", conditions: [{ indicator: "trend", window: 60, operator: "gt", threshold: "0" }] },
  sell: { mode: "any", conditions: [{ indicator: "trend", window: 60, operator: "lte", threshold: "0" }] },
  allocation: 100,
});
export function ruleSummary(rule: Rule, definitions: ConditionDefinition[], categories: JourneyCatalog["sentiment_categories"]) {
  const group = (value: ConditionGroup) => value.conditions.map((condition) => {
    const definition = definitions.find((row) => row.key === condition.indicator);
    const category = categories.find((row) => row.key === condition.category_key);
    return `${category ? `${category.name} · ` : ""}${definition?.label ?? condition.indicator}${condition.window ? `（${condition.window}个交易日）` : ""}${operatorNames[condition.operator]}${condition.threshold}${definition?.unit ?? ""}`;
  }).join(value.mode === "all" ? "，并且" : "，或者");
  return `空仓时，${group(rule.buy)}则买入；持仓时，${group(rule.sell)}则退出。使用${rule.allocation === 50 ? "一半资金，另一半保留现金" : "全部资金"}，收盘判断，下一交易日开盘模拟执行；持仓期间不每日补减仓。`;
}

export function journeyUrl(page: string, code?: string, extra: Record<string, string> = {}) {
  return `?${new URLSearchParams({ page, ...(code ? { code, object: `etf:${code}` } : {}), ...extra })}`;
}

export function activationMessage(version: SavedStrategy, positions?: AccountHoldings) {
  const position = positions?.items.find((row) => row.instrument_code === version.instrument_code);
  const quantity = positions?.as_of ? `${position?.current_amount ?? 0} 份（源日期 ${positions.as_of}，是否适用须在生成计划时重新核验）` : "未取得完整仓位证据，数量待核验";
  return `规则当前要求${version.readiness?.target == null ? "暂不可判断" : version.readiness.target ? "持有" : "空仓"}；你的真实仓位：${quantity}。${version.readiness?.reason ?? "等待下一次依赖检查"}。下次自动运行：${version.next_run ? stamp(version.next_run) : "尚未安排，请检查任务5开关"}。计划不是订单或成交。`;
}
