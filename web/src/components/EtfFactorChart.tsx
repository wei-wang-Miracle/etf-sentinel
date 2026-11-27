import { useEffect, useMemo, useRef, useState, type ComponentProps, type ReactNode } from "react";
import AppLink from "./AppLink";
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
const DEFAULT_FACTORS = ["turning_bottom", "turning_top", "close_above_prior_high"];

export default function EtfFactorChart({ history, start, end, theme, instrumentCode, trades = NO_TRADES, controls }: Props) {
  const catalog = useApiResource<FactorCatalog>("/factors");
  const markers = useApiResource<FactorDates>(`/candles/${instrumentCode}/factors?start=${start}&end=${end}`);
  const [visible, setVisible] = useState(DEFAULT_FACTORS);
  const [open, setOpen] = useState(false);
  const [inspectedId, setInspectedId] = useState<string>("");
  const anchorRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const visibleCatalog = useMemo(
    () => (catalog.data?.factors ?? []).filter((factor) => factor.chart_visible),
    [catalog.data],
  );
  const selectedFactors = useMemo(
    () => visibleCatalog.filter((factor) => visible.includes(factor.id)),
    [visibleCatalog, visible],
  );
  const inspectedFactor = useMemo(
    () => visibleCatalog.find((factor) => factor.id === inspectedId) ?? selectedFactors[0] ?? visibleCatalog[0],
    [visibleCatalog, inspectedId, selectedFactors],
  );

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const events = useMemo(() => markers.data?.events.filter(({ factor_id }) => visible.includes(factor_id)), [markers.data, visible]);
  const rows = useMemo(() => history.filter((row) => row.date >= start && row.date <= end), [end, history, start]);

  return <>
    <div className="chart-local-controls turning-controls">
      <div className="factor-toolbar-left">
        <div className="factor-anchor" ref={anchorRef}>
          <button
            ref={triggerRef}
            type="button"
            className="factor-trigger"
            aria-expanded={open}
            aria-haspopup="dialog"
            onClick={() => setOpen((old) => !old)}
          >
            因子标记 · 已选 {visible.length} 项
          </button>
          {open && (
            <div className="factor-popover" role="dialog" aria-label="选择因子标记">
              <div className="factor-popover-header">
                <strong>可观察因子图层</strong>
                <div className="factor-popover-actions">
                  <button type="button" onClick={() => setVisible(DEFAULT_FACTORS)}>恢复默认</button>
                  <button type="button" disabled={!visible.length} onClick={() => setVisible([])}>清空</button>
                  <button type="button" onClick={() => { setOpen(false); triggerRef.current?.focus(); }}>收起</button>
                </div>
              </div>
              {catalog.loading && <p className="empty" role="status">正在读取因子目录…</p>}
              {catalog.error && <p className="notice warning">因子目录暂不可用 · {catalog.error} <button type="button" onClick={catalog.retry}>重试目录</button></p>}
              {!!visibleCatalog.length && (
                <div className="factor-grid">
                  {visibleCatalog.map((factor) => (
                    <label
                      key={factor.id}
                      className="factor-option"
                      onMouseEnter={() => setInspectedId(factor.id)}
                      onFocus={() => setInspectedId(factor.id)}
                    >
                      <input
                        type="checkbox"
                        checked={visible.includes(factor.id)}
                        onChange={(event) => {
                          const checked = event.target.checked;
                          setVisible((ids) => checked ? [...ids, factor.id] : ids.filter((id) => id !== factor.id));
                          setInspectedId(factor.id);
                        }}
                      />
                      <span className="factor-option-meta">
                        <span>{factor.name}</span>
                        <span className="factor-option-cat">{factor.category}</span>
                      </span>
                    </label>
                  ))}
                </div>
              )}
              <div className="factor-meaning-bar">
                {inspectedFactor ? (
                  <>
                    <strong>{inspectedFactor.name}</strong>
                    <span>{inspectedFactor.meaning}</span>
                  </>
                ) : (
                  <span>因子标记仅供观察，不是买卖信号。</span>
                )}
              </div>
            </div>
          )}
        </div>
        {!!selectedFactors.length && (
          <div className="factor-active-chips" aria-label="已选因子">
            {selectedFactors.map((factor) => (
              <button
                key={factor.id}
                type="button"
                className="factor-chip-tag"
                aria-label={`移除 ${factor.name}`}
                onClick={() => setVisible((ids) => ids.filter((id) => id !== factor.id))}
              >
                <span>{factor.name}</span>
                <span aria-hidden="true">×</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="factor-toolbar-right">{controls}</div>
    </div>
    <KLine rows={rows} historyRows={history} theme={theme} trades={trades} factorEvents={events} frontAdjusted />
    {markers.loading ? <p className="muted" role="status">正在读取因子标记…</p>
      : markers.error ? <p className="notice warning" role="status">因子标记暂不可用 · {markers.error} {markers.error.includes("权益资料") && <AppLink href={dataManagementUrl("jobs", "etf", instrumentCode)}>到行情任务批量更新权益资料</AppLink>} <button type="button" onClick={markers.retry}>重试标点</button></p>
        : markers.data && <p className="muted" role="status">
          {markers.data.data_cutoff ? `因子标记 · 本地日行情及已核验权益 · 数据截止 ${markers.data.data_cutoff}` : "所选区间暂无可核验的因子数据"}
          {markers.data.partial ? " · 部分行情日期尚未核验权益" : ""}
          {markers.data.warmup_insufficient ? " · 部分因子预热不足" : ""}
          {markers.data.data_cutoff && !events?.length ? " · 所选因子在区间内无标记" : ""}
        </p>}
  </>;
}
