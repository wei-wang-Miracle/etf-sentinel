export type Parameter = {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
};
export type Strategy = {
  key: string;
  name: string;
  version: string;
  description: string;
  parameters: Parameter[];
};
export type ResearchInstrument = {
  instrument_code: string;
  instrument_name: string;
  count: number;
  first_date: string | null;
  last_date: string | null;
  default_start: string | null;
  source_checked_through: string | null;
};
export type Catalog = {
  strategies: Strategy[];
  instruments: ResearchInstrument[];
  engine_version: string;
};
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
export type Experiment = {
  id: number;
  instrument_code: string;
  strategy_key: string;
  created_at: string;
  input_sha256: string;
  settings: Record<string, string | number | Record<string, number>>;
  engine_version: string;
  strategy_version: string;
  actual_start: string;
  actual_end: string;
  metrics: Metrics;
};
export type Result = Experiment & {
  result: { strategy: Account; benchmark: Account };
  provenance: {
    source_url: string;
    collected_at: string;
    checked_through_date: string;
    market_source: string;
  };
  warmup_count: number;
  data_cutoff: string;
  calendar_version: string;
};
export const percent = (value: number | null) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export const experimentParameters = (
  run: Experiment,
): Record<string, number> =>
  typeof run.settings.parameters === "object"
    ? run.settings.parameters
    : { window: Number(run.settings.window) };
export const parameterSummary = (run: Experiment, strategies?: Strategy[]) => {
  const rule = strategies?.find((s) => s.key === run.strategy_key);
  const parameters = experimentParameters(run);
  return (
    rule?.parameters.map((p) => `${p.label} ${parameters[p.key]}`).join("、") ??
    "已保存参数"
  );
};
