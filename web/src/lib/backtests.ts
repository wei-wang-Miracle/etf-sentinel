export type Metrics = {
  total_return: number;
  annual_return: number | null;
  max_drawdown: number;
  annual_volatility: number | null;
  trade_count: number;
  commission: string;
  slippage_cost: string;
  turnover: number;
  final_equity: string;
};
export type DailyAccount = {
  trade_date: string;
  cash: string;
  quantity: number;
  equity: string;
  nav: number;
  drawdown: number;
  position_weight: number;
  reason: string;
  execution_note: string;
  dividend_receivable: string;
};
export type Trade = {
  trade_date: string;
  signal_date: string | null;
  side: string;
  quantity: number;
  price: string;
  commission: string;
  slippage_cost: string;
  reason: string;
};
export type Account = {
  daily: DailyAccount[];
  trades: Trade[];
  metrics: Metrics;
};
export const percent = (value: number | null) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;