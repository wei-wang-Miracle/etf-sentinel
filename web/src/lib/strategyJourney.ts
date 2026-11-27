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
export type StrategyDefinition = {
  id: string;
  name: string;
  description: string;
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
