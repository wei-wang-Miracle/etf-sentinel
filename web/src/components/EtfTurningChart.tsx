import { useMemo, type ComponentProps, type ReactNode } from "react";
import KLine, { type TurningEvent } from "./KLine";
import { useApiResource } from "../lib/useApiResource";
import { dataManagementUrl } from "../lib/navigation";

export type TurningChartDisplay = { showBottom: boolean; showTop: boolean };

type Props = {
  history: ComponentProps<typeof KLine>["rows"];
  start: string;
  end: string;
  theme: string;
  instrumentCode: string;
  trades?: ComponentProps<typeof KLine>["trades"];
  controls?: ReactNode;
  display: TurningChartDisplay;
  onDisplayChange: (display: TurningChartDisplay) => void;
};

type StrategyConfirmations = {
  events: TurningEvent[];
  data_cutoff: string | null;
  partial: boolean;
};

const NO_TRADES: NonNullable<Props["trades"]> = [];

export default function EtfTurningChart({
  history,
  start,
  end,
  theme,
  instrumentCode,
  trades = NO_TRADES,
  controls,
  display,
  onDisplayChange,
}: Props) {
  const strategy = useApiResource<StrategyConfirmations>(
    `/candles/${instrumentCode}/turning-events?start=${start}&end=${end}`,
  );
  const visibleEvents = useMemo(
    () => strategy.data?.events.filter((event) => (
      event.kind === "bottom" ? display.showBottom : display.showTop
    )),
    [display.showBottom, display.showTop, strategy.data?.events],
  );
  const rows = useMemo(
    () => history.filter((row) => row.date >= start && row.date <= end),
    [end, history, start],
  );

  return <>
    <div className="chart-local-controls turning-controls">
      <label><input type="checkbox" checked={display.showBottom} onChange={(event) => onDisplayChange({ ...display, showBottom: event.target.checked })} /><span className="turning-bottom">▲ 底部确认</span></label>
      <label><input type="checkbox" checked={display.showTop} onChange={(event) => onDisplayChange({ ...display, showTop: event.target.checked })} /><span className="turning-top">▼ 顶部确认</span></label>
      {controls}
    </div>
    <KLine
      rows={rows}
      historyRows={history}
      theme={theme}
      trades={trades}
      turningEvents={visibleEvents}
      frontAdjusted
    />
    {strategy.loading ? <p className="muted" role="status">正在读取顶底确认因子…</p>
      : strategy.error ? <p className="notice warning" role="status">顶底确认因子暂不可用 · {strategy.error} {strategy.error.includes("权益资料") && <a href={dataManagementUrl("jobs", "etf", instrumentCode)}>到行情任务批量更新权益资料</a>} <button type="button" onClick={strategy.retry}>重试标点</button></p>
        : strategy.data && <p className="muted" role="status">
          {strategy.data.data_cutoff ? `顶底确认因子 · 本地日行情及已核验权益 · 数据截止 ${strategy.data.data_cutoff}` : "所选区间暂无可核验的顶底确认数据"}
          {strategy.data.partial ? " · 部分行情日期尚未核验权益" : ""}
          {strategy.data.data_cutoff && !strategy.data.events.length ? " · 区间内无确认事件" : ""}
        </p>}
    {instrumentCode === "518880" && <p className="muted">该 ETF 使用通用顶底参数模板，尚未进行黄金 ETF 专项验证。</p>}
  </>;
}
