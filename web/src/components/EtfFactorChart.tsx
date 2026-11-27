import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import KLine, { type FactorEvent } from "./KLine";
import type { FactorIdentity } from "../lib/strategyJourney";
import { useApiResource } from "../lib/useApiResource";
import { dataManagementUrl } from "../lib/navigation";

type Props = {
  history: ComponentProps<typeof KLine>["rows"];
  start: string;
  end: string;
  theme: string;
  instrumentCode: string;
  trades?: ComponentProps<typeof KLine>["trades"];
  controls?: ReactNode;
};

type FactorDates = { events: FactorEvent[]; data_cutoff: string | null; partial: boolean; warmup_insufficient: boolean };
type FactorCatalog = { factors: (FactorIdentity & { chart_visible: boolean; output_type: string })[] };
const NO_TRADES: NonNullable<Props["trades"]> = [];

export default function EtfFactorChart({ history, start, end, theme, instrumentCode, trades = NO_TRADES, controls }: Props) {
  const catalog = useApiResource<FactorCatalog>("/factors");
  const markers = useApiResource<FactorDates>(`/candles/${instrumentCode}/factors?start=${start}&end=${end}`);
  const [visible, setVisible] = useState(["turning_bottom", "turning_top"]);
  const events = useMemo(() => markers.data?.events.filter(({ factor_id }) => visible.includes(factor_id)), [markers.data, visible]);
  const rows = useMemo(() => history.filter((row) => row.date >= start && row.date <= end), [end, history, start]);

  return <>
    <div className="chart-local-controls turning-controls">
      <details>
        <summary>因子标记 · 已选 {visible.length} 项</summary>
        {catalog.loading && <p role="status">正在读取因子目录…</p>}
        {catalog.error && <p className="notice warning">因子目录暂不可用 · {catalog.error} <button onClick={catalog.retry}>重试目录</button></p>}
        {catalog.data?.factors.filter((factor) => factor.chart_visible).map((factor) => <div key={factor.id}>
          <label><input type="checkbox" checked={visible.includes(factor.id)} onChange={(event) => {
            const checked = event.target.checked;
            setVisible((ids) => checked ? [...ids, factor.id] : ids.filter((id) => id !== factor.id));
          }} />{factor.name} · {factor.category}</label>
          <p className="muted">{factor.meaning}</p>
        </div>)}
        <p className="muted">因子标记仅供观察，不是买卖信号。</p>
      </details>
      {controls}
    </div>
    <KLine rows={rows} historyRows={history} theme={theme} trades={trades} factorEvents={events} frontAdjusted />
    {markers.loading ? <p className="muted" role="status">正在读取因子标记…</p>
      : markers.error ? <p className="notice warning" role="status">因子标记暂不可用 · {markers.error} {markers.error.includes("权益资料") && <a href={dataManagementUrl("jobs", "etf", instrumentCode)}>到行情任务批量更新权益资料</a>} <button onClick={markers.retry}>重试标点</button></p>
        : markers.data && <p className="muted" role="status">
          {markers.data.data_cutoff ? `因子标记 · 本地日行情及已核验权益 · 数据截止 ${markers.data.data_cutoff}` : "所选区间暂无可核验的因子数据"}
          {markers.data.partial ? " · 部分行情日期尚未核验权益" : ""}
          {markers.data.warmup_insufficient ? " · 部分因子预热不足" : ""}
          {markers.data.data_cutoff && !events?.length ? " · 所选因子在区间内无标记" : ""}
        </p>}
  </>;
}
