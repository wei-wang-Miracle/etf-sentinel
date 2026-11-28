import type { Account } from "./backtests";

export type ResearchSettings = {
  instrument_code: string;
  start_date: string;
  end_date: string;
  initial_cash: string;
  commission_rate: string;
  minimum_commission: string;
  slippage_bps: string;
};

export type FactorIdentity = {
  id: string;
  name: string;
  category: string;
  meaning: string;
};
export type StrategyEvidence = {
  scope_type: string;
  research_version: string;
  evidence_tier: string;
  adoptable: boolean;
  evidence_summary?: {
    source_candidate?: string;
    note?: string;
    development?: {
      completed: number;
      win_rate: number;
      profit_factor: number;
      drawdown: number;
      intra_positive?: string;
    };
    holdout?: {
      completed: number;
      win_rate: number;
      profit_factor: number;
      drawdown: number;
      intra_positive?: string;
    };
  };
};

export type StrategyDefinition = {
  id: string;
  name: string;
  description: string;
  adoptable?: boolean;
  scope_type?: "universal" | "category";
  bound_categories?: string[];
  adoptable_instruments?: string[];
  min_warmup_bars?: number;
  earliest_start_by_instrument?: Record<string, string | null>;
  evidence_by_category?: Record<string, StrategyEvidence>;
  supported_instruments: string[];
  factors: (FactorIdentity & { role: string })[];
};
export type StrategyAssignment = {
  id: number;
  strategy_id: string;
  instrument_code: string;
  comparison_id: number;
  active: boolean;
  adopted_at: string;
};
export type JourneyCatalog = {
  instruments: {
    instrument_code: string;
    instrument_name: string;
    research_category?: string;
    first_date: string | null;
    last_date: string | null;
    default_start: string | null;
    default_end: string | null;
    source_checked_through: string | null;
  }[];
  strategies: StrategyDefinition[];
  assignments: StrategyAssignment[];
};
export type ComparisonTrack = {
  key: string;
  name: string;
  strategy_id: string;
  status: string;
  reason?: string;
  backtest_id?: number;
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

export function journeyUrl(page: string, code?: string, extra: Record<string, string> = {}) {
  return `?${new URLSearchParams({ page, ...(code ? { code, object: `etf:${code}` } : {}), ...extra })}`;
}

export function isStrategyAdoptable(definition: StrategyDefinition | undefined, code?: string) {
  if (!definition) return false;
  if (code && definition.adoptable_instruments) {
    return definition.adoptable_instruments.includes(code);
  }
  return definition.adoptable !== false;
}

const EVIDENCE_TIER_LABELS: Record<string, string> = {
  cross_unit_verified: "跨指数验证 · 开放采用",
  single_unit_candidate: "单指数候选 · 开放采用",
  holdout_watch: "留出待观察 · 暂观察",
  rejected: "未达门槛 · 暂观察",
  baseline: "现行基准 · 开放采用",
};

export function evidenceForStrategy(definition: StrategyDefinition | undefined, category?: string) {
  if (!definition?.evidence_by_category) return undefined;
  if (category && definition.evidence_by_category[category]) {
    return definition.evidence_by_category[category];
  }
  return definition.evidence_by_category["通用"] ?? Object.values(definition.evidence_by_category)[0];
}

export function evidenceTierLabel(evidence: StrategyEvidence | undefined) {
  if (!evidence) return "";
  return EVIDENCE_TIER_LABELS[evidence.evidence_tier] ?? evidence.evidence_tier;
}

export function strategyScopeLabel(definition: StrategyDefinition) {
  if (definition.scope_type === "universal") return "通用策略";
  if (definition.bound_categories?.length) {
    return `分类绑定：${definition.bound_categories.join("、")}`;
  }
  return "分类策略";
}
