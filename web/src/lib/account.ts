export type AccountSyncRun = {
  id: number;
  status: string;
  range_start: string | null;
  range_end: string | null;
  fetched_count: number;
  stored_count: number;
  skipped_count: number;
  error_count: number;
  error_message: string | null;
  started_at: string;
  ended_at: string | null;
};

export type AccountSyncStatus = {
  latest: AccountSyncRun | null;
  runs: AccountSyncRun[];
};

export type AccountSyncSummary = {
  sync_run_id: number;
  status: string;
  range_start: string | null;
  range_end: string | null;
  fetched_count: number;
  stored_count: number;
  skipped_count: number;
  error_count: number;
  error_message: string | null;
};

export type AccountHolding = {
  instrument_code: string;
  instrument_name: string;
  current_amount: number;
  enable_amount: number;
  frozen_amount: number;
  uncome_buy_amount: number;
  uncome_sell_amount: number;
  cost_price: number | null;
  latest_close: number | null;
  latest_close_date: string | null;
  market_value: number | null;
  cost_value: number | null;
  unrealized_pnl: number | null;
  weight: number | null;
  data_date: string;
  source_etl_time: string | null;
  collected_at: string;
};

export type AccountHoldings = {
  as_of: string | null;
  items: AccountHolding[];
  summary: {
    holding_count: number;
    market_value: number | null;
    cost_value: number | null;
    unrealized_pnl: number | null;
    configured_only: boolean;
  };
};

export type AccountEntrust = {
  instrument_code: string;
  instrument_name: string;
  curr_date: string;
  curr_time: string | null;
  display_time: string | null;
  init_date: string | null;
  entrust_no: string;
  order_id: string | null;
  side: string;
  entrust_amount: number;
  entrust_price: number;
  entrust_type: string | null;
  business_amount: number;
  business_price: number;
  business_balance: number;
  withdraw_amount: number;
  entrust_status: string | null;
  fare_kind: string | null;
  fee_amount: number;
  data_date: string;
  source_etl_time: string | null;
};

export type AccountEntrusts = {
  start: string;
  end: string;
  count: number;
  items: AccountEntrust[];
};

export const syncStatusName: Record<string, string> = {
  running: "运行中",
  success: "成功",
  partial: "部分行错误",
  failed: "失败",
};

export const entrustStatusName = (row: AccountEntrust) => {
  if (row.business_amount > 0) return "成交";
  if (row.withdraw_amount > 0) return "撤单";
  return "未成交";
};
