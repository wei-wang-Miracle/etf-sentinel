import type { Account } from "./backtests";
export type Period = "development" | "validation";
export type Windows = Record<`${Period}_${"start" | "end"}`, string>;
export type Candidate = {
  key: string;
  name: string;
  allocation: number;
  strategy_key: string;
  strategy_version?: string;
  parameters: Record<string, number>;
};
export type Diagnostics = {
  longest_underwater_days: number;
  time_in_market: number;
  completed_rounds: number;
  open_rounds: number;
  sample_warning?: string | null;
  rounds?: { entry_date: string; exit_date: string; pnl: string }[];
};
export type Track = Account &
  Candidate & {
    diagnostics?: Diagnostics;
    same_exposure_benchmark?: Account | null;
  };
export type ResearchPeriod = {
  status: string;
  reason?: string;
  tracks: Track[];
  pareto_keys?: string[];
  failures?: { key: string; name: string; reason: string }[];
};
export type LabCatalog = {
  as_of: string | null;
  initial_cash_per_etf: string;
  rule_note: string;
  warnings: string[];
  suggested: Windows | null;
  items: {
    instrument_code: string;
    instrument_name: string;
    actual_quantity: string;
    available_quantity: string;
    holding_date: string;
    research_start: string | null;
    last_date: string | null;
    source_checked_through: string | null;
    factor_warning?: string | null;
    factors: {
      as_of: string;
      trend_above_ma60: boolean | null;
      momentum20: number | null;
      volatility20: number | null;
      source: string;
      note: string;
    } | null;
  }[];
};
export type Batch = {
  id: number;
  created_at: string;
  input: Windows & {
    holdings_as_of: string;
    initial_cash_per_etf: string;
    instruments: { instrument_code: string; instrument_name: string }[];
  };
  result: {
    instruments: {
      instrument_code: string;
      instrument_name: string;
      periods: Record<Period, ResearchPeriod>;
    }[];
    portfolio: Record<Period, ResearchPeriod>;
    warnings: string[];
  };
};
export type Observation = {
  id: number;
  instrument_code: string;
  research_batch_id: number;
  created_at: string;
  active: boolean;
  rule: Candidate;
};
export type PlanSignal = {
  id: number;
  instrument_code: string;
  observation_id: number;
  generated_at: string;
  data_cutoff: string;
  execution_date: string;
  skip_note: string | null;
  plan: {
    action: string;
    actual_quantity: string;
    available_quantity: string;
    target_quantity: number;
    position_basis?: string;
    requested_quantity: string;
    planned_quantity: string;
    reference_price: string;
    holding_date: string;
    reason: string;
    factors?: LabCatalog["items"][number]["factors"];
    indicators?: Record<string, string | number | null>;
    input_sha256?: string;
    funding_check_required: boolean;
    warnings: string[];
  };
  execution: {
    status: string;
    confirmed_quantity: string;
    links: {
      id: number;
      entrust_no: string;
      confirmed_trade_date: string;
      current_amount: string;
      source_revised: boolean;
      source_valid: boolean;
      confirmation_note: string;
    }[];
  };
};
export type EntrustCandidate = {
  curr_date: string;
  entrust_no: string;
  quantity: string;
  price: string;
  fee_amount: string;
  note: string;
};
export type ObservationReview = {
  status: string;
  reason?: string;
  adopted_at: string;
  label: string;
  data_cutoff?: string;
  result?: { strategy: Account; benchmark: Account };
};
export const executionNames: Record<string, string> = {
  skipped: "主动跳过",
  no_action: "无需调整",
  unconfirmed: "尚未确认",
  none: "关联成交为零",
  partial: "部分执行",
  complete: "数量一致",
  excess: "超额执行",
};
