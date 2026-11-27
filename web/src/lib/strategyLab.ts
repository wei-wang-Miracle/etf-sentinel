export type PlanSignal = {
  id: number;
  instrument_code: string;
  assignment_id: number;
  strategy_id: string;
  strategy_name: string;
  generated_at: string;
  data_cutoff: string;
  execution_date: string;
  skip_note: string | null;
  plan: {
    action: string;
    actual_quantity: string | null;
    available_quantity: string | null;
    target_quantity: number;
    position_basis?: string;
    requested_quantity: string;
    planned_quantity: string;
    reference_price: string;
    holding_date: string;
    reason: string;
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
export const executionNames: Record<string, string> = {
  skipped: "主动跳过",
  no_action: "无需调整",
  unconfirmed: "尚未确认",
  none: "关联成交为零",
  partial: "部分执行",
  complete: "数量一致",
  excess: "超额执行",
};
