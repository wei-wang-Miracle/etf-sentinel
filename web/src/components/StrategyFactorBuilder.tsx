import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { doubleWindowIndicators, eventIndicators, operatorNames, type Condition, type ConditionDefinition, type Coverage, type JourneyCatalog, type Rule } from "../lib/strategyJourney";
import { strategyIndicatorHelp } from "../lib/strategyIndicatorHelp";
import "../styles/strategy-factor-builder.css";

const coverageNames: Record<string, string> = { historical: "可用于历史回测", revised: "修订历史研究", unavailable: "暂不可用" };
const factorType = "application/x-etf-strategy-factor";
type Side = "buy" | "sell";
const sources = [
  ["etf_daily", "ETF 日 K"], ["index_valuation", "关联指数估值"],
  ["sentiment", "市场／行业恐贪"], ["national_team", "国家队持仓估算"],
];
function sourceOf(definition: ConditionDefinition) {
  return definition.source ?? (definition.key === "sentiment" ? "sentiment" : definition.key === "national_team_change" ? "national_team" : definition.evidence_type === "historical" ? "etf_daily" : "index_valuation");
}

export default function StrategyFactorBuilder({ rule, catalog, coverage, disabled, onChange }: {
  rule: Rule; catalog: JourneyCatalog; coverage?: Coverage; disabled: boolean;
  onChange: (rule: Rule) => void;
}) {
  const dragged = useRef<string | null>(null);
  const [over, setOver] = useState<Side | null>(null);
  const [help, setHelp] = useState<ConditionDefinition>();
  const dialog = useRef<HTMLDialogElement>(null);
  const helpTitle = useId();
  const lists = useRef<Record<Side, HTMLDivElement | null>>({ buy: null, sell: null });
  const previousCounts = useRef({ buy: rule.buy.conditions.length, sell: rule.sell.conditions.length });
  useEffect(() => {
    for (const side of ["buy", "sell"] as const) {
      const count = rule[side].conditions.length;
      const list = lists.current[side];
      if (list && count > previousCounts.current[side]) list.scrollTop = list.scrollHeight;
      previousCounts.current[side] = count;
    }
  }, [rule.buy.conditions.length, rule.sell.conditions.length]);

  function add(side: Side, definition: ConditionDefinition) {
    if (disabled || rule[side].conditions.length >= 20) return;
    const condition: Condition = {
      indicator: definition.key, operator: eventIndicators.has(definition.key) ? "cross_up" : "gt", threshold: definition.unit === "倍" ? "1" : "0",
      ...(doubleWindowIndicators.has(definition.key) ? { long_window: 20 } : {}),
      ...(definition.key === "ma_slope" ? { lag: 5 } : {}),
      ...(definition.window ? { window: doubleWindowIndicators.has(definition.key) ? 5 : 20 } : {}),
      ...(definition.key === "sentiment" ? { category_key: "" } : {}),
    };
    onChange({ ...rule, [side]: { ...rule[side], conditions: [...rule[side].conditions, condition] } });
  }
  function update(side: Side, index: number, patch: Partial<Condition>) {
    onChange({ ...rule, [side]: { ...rule[side], conditions: rule[side].conditions.map((row, i) => i === index ? { ...row, ...patch } : row) } });
  }
  function showHelp() {
    setHelp(catalog.conditions[0]);
    dialog.current?.showModal();
  }
  function acceptDrag(event: DragEvent, side: Side) {
    if (disabled || !dragged.current || rule[side].conditions.length >= 20) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setOver(side);
  }
  const explanation = help && strategyIndicatorHelp[help.key];
  const helpCoverage = coverage?.conditions.find((item) => item.key === help?.key);

  return <>
    <div className="factor-workspace">
      <section className="factor-library" aria-label="全部指标">
        <header><h2 title="拖入买卖条件区，或点击买／卖添加；可重复添加同一指标">全部指标 <span className="muted">{catalog.conditions.length}</span></h2><button type="button" disabled={disabled} onClick={showHelp}>指标说明</button></header>
        <div className="factor-library-scroll" tabIndex={0} aria-label="按来源浏览指标">
          {sources.map(([source, title]) => <section className="factor-source-section" aria-label={title} key={source}>
          <h3>{title}<span className="mono muted">{catalog.conditions.filter((item) => sourceOf(item) === source).length}</span></h3>
          <ul className="factor-list">
          {catalog.conditions.filter((item) => sourceOf(item) === source).map((definition) => {
            const available = coverage?.conditions.find((item) => item.key === definition.key);
            return <li key={definition.key} draggable={!disabled} className="factor-source" onDragStart={(event) => {
              if (disabled) { event.preventDefault(); return; }
              dragged.current = definition.key;
              event.dataTransfer.setData(factorType, definition.key);
              event.dataTransfer.effectAllowed = "copy";
            }} onDragEnd={() => { dragged.current = null; setOver(null); }}>
              <span className="factor-grip" aria-hidden="true">⠿</span>
              <span className="factor-name" title={`${definition.description}${available?.reason ? `；${available.reason}` : ""}`}>
                <span>{definition.display_label ?? definition.label}</span>
                {available?.status === "unavailable" && <span className="factor-unavailable">暂不可用</span>}
              </span>
              <div className="factor-source-actions">
                <button type="button" disabled={disabled || rule.buy.conditions.length >= 20} aria-label={`将${definition.display_label ?? definition.label}加入买入条件`} onClick={() => add("buy", definition)}>买</button>
                <button type="button" disabled={disabled || rule.sell.conditions.length >= 20} aria-label={`将${definition.display_label ?? definition.label}加入卖出条件`} onClick={() => add("sell", definition)}>卖</button>
              </div>
            </li>;
          })}
        </ul></section>)}
        </div>
      </section>
      {(["buy", "sell"] as const).map((side) => {
        const group = rule[side];
        const name = side === "buy" ? "买入" : "卖出";
        const duplicate = group.conditions.some((row, i) => group.conditions.some((other, j) => i !== j && row.indicator === other.indicator && row.window === other.window && row.long_window === other.long_window && row.lag === other.lag && row.operator === other.operator && row.threshold === other.threshold && row.category_key === other.category_key));
        return <fieldset key={side} disabled={disabled} className={`factor-group ${over === side ? "factor-drop-active" : ""}`} onDragOver={(event) => acceptDrag(event, side)} onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(null);
        }} onDrop={(event) => {
          event.preventDefault(); setOver(null);
          const key = event.dataTransfer.getData(factorType);
          const definition = catalog.conditions.find((item) => item.key === key);
          if (key === dragged.current && definition) add(side, definition);
          dragged.current = null;
        }}>
          <legend>{side === "buy" ? "什么时候买" : "什么时候卖"}</legend>
          <div className="factor-group-controls"><label>触发方式<select value={group.mode} onChange={(event) => onChange({ ...rule, [side]: { ...group, mode: event.target.value as "all" | "any" } })}><option value="all">全部条件满足</option><option value="any">任一条件满足</option></select></label><span className="muted mono">{group.conditions.length} / 20</span></div>
          <div className="factor-conditions" ref={(node) => { lists.current[side] = node; }} tabIndex={0} aria-label={`${name}条件列表`}>
            {group.conditions.map((row, index) => {
              const definition = catalog.conditions.find((item) => item.key === row.indicator);
              const available = coverage?.conditions.find((item) => item.key === row.indicator);
              return <article className="factor-condition" key={index} aria-label={`${name}条件${index + 1}`}>
                <header><h3><span className="muted mono">{index + 1}.</span> {definition?.display_label ?? definition?.label ?? row.indicator}{available?.status === "unavailable" && <span className="factor-unavailable">暂不可用</span>}</h3><div>
                  <button type="button" aria-label={`删除${name}条件${index + 1}`} disabled={group.conditions.length === 1} onClick={() => onChange({ ...rule, [side]: { ...group, conditions: group.conditions.filter((_, i) => i !== index) } })}>删除</button>
                </div></header>
                <div className={`factor-parameters ${eventIndicators.has(row.indicator) ? "factor-event-parameters" : ""}`}>
                  {definition?.window && <label>{doubleWindowIndicators.has(row.indicator) ? "短窗口交易日" : "回看交易日"}<input type="number" min={2} max={row.long_window ? row.long_window - 1 : 250} required value={row.window ?? 20} onChange={(event) => update(side, index, { window: Number(event.target.value) })} /></label>}
                  {doubleWindowIndicators.has(row.indicator) && <label>长窗口交易日<input type="number" min={(row.window ?? 5) + 1} max={250} required value={row.long_window ?? 20} onChange={(event) => update(side, index, { long_window: Number(event.target.value) })} /></label>}
                  {row.indicator === "ma_slope" && <label>比较间隔交易日<input type="number" min={1} max={250} required value={row.lag ?? 5} onChange={(event) => update(side, index, { lag: Number(event.target.value) })} /></label>}
                  {row.indicator === "sentiment" && <label className="factor-category">市场背景类别<select required value={row.category_key ?? ""} onChange={(event) => update(side, index, { category_key: event.target.value })}><option value="">明确选择类别</option>{catalog.sentiment_categories.map((category) => <option key={category.key} value={category.key}>{category.name}</option>)}</select></label>}
                  <label>比较<select value={row.operator} onChange={(event) => update(side, index, { operator: event.target.value as Condition["operator"] })}>{Object.entries(operatorNames).filter(([key]) => eventIndicators.has(row.indicator) === key.startsWith("cross_")).map(([key, label]) => <option key={key} value={key}>{row.indicator === "breakout" ? (key === "cross_up" ? "上破前期最高收盘" : "下破前期最低收盘") : label}</option>)}</select></label>
                  {!eventIndicators.has(row.indicator) && <label>阈值（{definition?.unit ?? "数值"}）<input required type="number" step="any" value={row.threshold} onChange={(event) => update(side, index, { threshold: event.target.value })} /></label>}
                </div>
              </article>;
            })}
            <p className="factor-drop-hint">{group.conditions.length >= 20 ? "已达 20 条上限，删除后可继续添加" : `将指标拖到这里，添加${name}条件`}</p>
            {duplicate && <p className="factor-warning">存在相同指标与窗口，可能与已有条件重复。</p>}
          </div>
        </fieldset>;
      })}
    </div>
    <dialog ref={dialog} className="factor-help-dialog" aria-labelledby={helpTitle} onClose={() => setHelp(undefined)}>
      <header><h2 id={helpTitle}>指标说明</h2><button type="button" autoFocus onClick={() => dialog.current?.close()}>关闭</button></header>
      <p className="factor-help-intro">拖入买入或卖出区，或点“买／卖”复制添加条件；同一指标可设置多组参数。模板及默认参数仅作研究起点，不代表推荐。</p>
      <label className="factor-help-picker">查看指标<select value={help?.key ?? ""} onChange={(event) => setHelp(catalog.conditions.find((item) => item.key === event.target.value))}>{catalog.conditions.map((item) => <option key={item.key} value={item.key}>{item.display_label ?? item.label}</option>)}</select></label>
      <p className="factor-help-coverage">{help && <>{sources.find(([key]) => key === sourceOf(help))?.[1]} · </>}{helpCoverage ? <>{coverageNames[helpCoverage.status] ?? helpCoverage.status} · {helpCoverage.first_date ?? "无覆盖"}—{helpCoverage.last_date ?? "无覆盖"}{helpCoverage.reason ? ` · ${helpCoverage.reason}` : ""}</> : "覆盖资料未取得，回测仍须核验"}</p>
      {explanation && <dl>{[
        ["投资含义", explanation.meaning], ["如何理解", explanation.interpretation],
        ["计算方式", explanation.calculation], ["数据来源与口径", explanation.source], ["使用边界", explanation.caveat],
      ].map(([title, content]) => <div key={title}><dt>{title}</dt><dd>{content}</dd></div>)}</dl>}
      <p className="factor-help-intro">研究资金不等于账户现金；持有不每日调份额，保留现金不补仓。历史来源可能修订，未证明原时点可得；数据覆盖和预热要求仍须在回测时逐日核验。</p>
    </dialog>
  </>;
}
