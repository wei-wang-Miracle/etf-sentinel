import type { Account } from "./backtests";
import type { AccountHoldings } from "./account";
import { stamp } from "./api";

export type ResearchSettings = {
  instrument_code: string;
  start_date: string;
  end_date: string;
  initial_cash: string;
  commission_rate: string;
  minimum_commission: string;
  slippage_bps: string;
};

export type TemplateRule = Record<string, string | number | boolean | null>;
export type TurningProfile = {
  group: string;
  group_name: string;
  parameters: Record<string, number>;
};
export type TemplateDefinition = {
  id: string;
  version: string;
  name: string;
  status: string;
  description: string;
  supported_instruments: string[];
  rules_by_instrument?: Record<string, TemplateRule>;
  turning_profiles_by_instrument?: Record<string, TurningProfile>;
  note: string;
};
export type TemplateSnapshot = Omit<TemplateDefinition, "description" | "supported_instruments" | "rules_by_instrument" | "turning_profiles_by_instrument"> & {
  instrument_code?: string;
  group?: string;
  description?: string;
  rule: TemplateRule;
  turning: TurningProfile;
  algorithm_version: string;
  turning_version: string;
};
export type SavedStrategy = {
  id: number;
  strategy_id: number;
  algorithm_template_id: string | null;
  name: string;
  version: number;
  instrument_code: string;
  template: TemplateSnapshot;
  settings: ResearchSettings;
  backtest_id: number;
  comparison_id?: number | null;
  active: boolean;
  observation_id: number | null;
  created_at: string;
  readiness?: { status: string; target?: number; reason?: string; data_cutoff?: string };
  next_run?: string | null;
};
export type JourneyCatalog = {
  instruments: {
    instrument_code: string;
    instrument_name: string;
    first_date: string | null;
    last_date: string | null;
    default_start: string | null;
    default_end: string | null;
    source_checked_through: string | null;
  }[];
  templates: TemplateDefinition[];
};
export type ComparisonTrack = {
  key: string;
  name: string;
  version_id?: number | null;
  status: string;
  reason?: string;
  backtest_id?: number;
  template?: TemplateSnapshot | null;
  allocation?: 100;
  account?: Account;
  diagnostics?: {
    time_in_market?: number;
    completed_rounds?: number;
    open_rounds?: number;
    rounds?: { entry_date: string; exit_date: string; pnl: string | number }[];
    sample_warning?: string | null;
  };
};
export type Comparison = {
  id: number;
  instrument_code: string;
  created_at: string;
  settings: ResearchSettings;
  input_sha256: string;
  tracks: ComparisonTrack[];
  complete: boolean;
  data_cutoff?: string | null;
  note?: string | null;
  market_rows: { trade_date: string; open: string; high: string; low: string; close: string; volume: string; source_updated_at: string | null; collected_at: string }[];
};

export function templateKey(template: Pick<TemplateDefinition, "id" | "version">) {
  return `${template.id}:${template.version}`;
}

export function journeyUrl(page: string, code?: string, extra: Record<string, string> = {}) {
  return `?${new URLSearchParams({ page, ...(code ? { code, object: `etf:${code}` } : {}), ...extra })}`;
}

export function activationMessage(version: SavedStrategy, positions?: AccountHoldings) {
  const position = positions?.items.find((row) => row.instrument_code === version.instrument_code);
  const quantity = positions?.as_of && position ? `${position.current_amount} 份（源日期 ${positions.as_of}，是否适用须在生成计划时重新核验）` : "未取得完整仓位证据，数量待核验";
  return `规则当前要求${version.readiness?.target == null ? "暂不可判断" : version.readiness.target ? "持有" : "空仓"}；你的真实仓位：${quantity}。${version.readiness?.reason ?? "等待下一次依赖检查"}。下次自动运行：${version.next_run ? stamp(version.next_run) : "尚未安排，请检查任务5开关"}。计划不是订单或成交。`;
}
