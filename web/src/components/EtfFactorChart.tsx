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

type FactorDates = {
  events: FactorEvent[];
  data_cutoff: string | null;
  partial: boolean;
  warmup_insufficient: boolean;
  external_factor_context?: {
    valuation_index_codes?: string[];
    coverage?: { valuation?: { available?: boolean } };
    benchmark?: { available?: boolean };
  };
};
type FactorCatalog = { factors: (FactorIdentity & { chart_visible: boolean; output_type: string })[] };
const NO_TRADES: NonNullable<Props["trades"]> = [];
const DEFAULT_FACTORS = ["turning_bottom", "turning_top", "oversold_recovery"];
const CATEGORY_ORDER = [
  "结构确认", "趋势状态", "趋势转折", "趋势走弱", "均线位置", "趋势回踩",
  "突破事件", "突破确认", "反转确认", "价格确认", "超跌状态", "波动率状态",
  "兑现状态", "兑现确认", "外部估值", "外部情绪", "全市场环境", "相对强弱",
];

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
  const factorGroups = useMemo(() => {
    const groups = new Map<string, typeof visibleCatalog>();
    for (const factor of visibleCatalog) {
      const items = groups.get(factor.category) ?? [];
      items.push(factor);
      groups.set(factor.category, items);
    }
    return [...groups.entries()].sort(([left], [right]) => {
      const leftOrder = CATEGORY_ORDER.indexOf(left);
      const rightOrder = CATEGORY_ORDER.indexOf(right);
      return (leftOrder < 0 ? CATEGORY_ORDER.length : leftOrder)
        - (rightOrder < 0 ? CATEGORY_ORDER.length : rightOrder)
        || left.localeCompare(right, "zh-CN");
    });
  }, [visibleCatalog]);
  const selectedNeedsIndex = selectedFactors.some(
    (factor) => factor.category === "外部估值" || factor.category === "相对强弱",
  );
  const indexUnmapped = selectedNeedsIndex
    && markers.data?.external_factor_context?.valuation_index_codes?.length === 0;

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
                <div className="factor-groups">
                  {factorGroups.map(([category, factors]) => (
                    <section className="factor-group" role="group" aria-label={category} key={category}>
                      <div className="factor-group-header">
                        <strong>{category}</strong>
                        <span>
                          <button
                            type="button"
                            aria-label={`选择 ${category} 全部`}
                            disabled={factors.every((factor) => visible.includes(factor.id))}
                            onClick={() => setVisible((ids) => [...new Set([...ids, ...factors.map((factor) => factor.id)])])}
                          >全选</button>
                          <button
                            type="button"
                            aria-label={`清空 ${category}`}
                            disabled={!factors.some((factor) => visible.includes(factor.id))}
                            onClick={() => setVisible((ids) => ids.filter((id) => !factors.some((factor) => factor.id === id)))}
                          >清空</button>
                        </span>
                      </div>
                      <div className="factor-grid">
                        {factors.map((factor) => (
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
                            </span>
                          </label>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
              {indexUnmapped && <p className="factor-context-warning">该 ETF 尚未映射指数，外部估值及相对强弱标记不可用 <AppLink href={dataManagementUrl("instruments")}>前往标的配置</AppLink></p>}
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
      : markers.error ? <p className="notice warning" role="status">因子标记暂不可用 · {markers.error} {markers.error.includes("权益资料") ? <AppLink href={dataManagementUrl("jobs", "etf", instrumentCode)}>到行情任务批量更新权益资料</AppLink> : markers.error.includes("行情") ? <AppLink href={dataManagementUrl("jobs", "etf", instrumentCode)}>到行情任务核验并补全行情</AppLink> : null} <button type="button" onClick={markers.retry}>重试标点</button></p>
        : markers.data && <p className="muted" role="status">
          {markers.data.data_cutoff ? `因子标记 · 本地日行情及已核验权益 · 数据截止 ${markers.data.data_cutoff}` : "所选区间暂无可核验的因子数据"}
          {markers.data.partial ? " · 部分行情日期尚未核验权益" : ""}
          {markers.data.warmup_insufficient ? " · 部分因子预热不足" : ""}
          {markers.data.data_cutoff && !events?.length ? " · 所选因子在区间内无标记" : ""}
        </p>}
  </>;
}
