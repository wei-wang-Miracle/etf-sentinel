import { useMemo, useState, type ComponentProps, type ReactNode } from "react";
import KLine from "./KLine";
import { calculateTurningPoints, DEFAULT_TURNING_OPTIONS, evaluateTurningPoints, TURNING_VERSION } from "../lib/turningPoints";
import { turningProfile } from "../lib/turningCategories";

type Props = {
  history: ComponentProps<typeof KLine>["rows"]; start: string; end: string; theme: string; instrumentCode: string;
  trades?: ComponentProps<typeof KLine>["trades"]; controls?: ReactNode;
};
const percent = (value: number | null) => value == null ? "—" : `${(value * 100).toFixed(1)}%`;
const NO_TRADES: NonNullable<Props["trades"]> = [];

export default function EtfTurningChart({ history, start, end, theme, instrumentCode, trades = NO_TRADES, controls }: Props) {
  const [showBottom, setShowBottom] = useState(true);
  const [showTop, setShowTop] = useState(true);
  const [horizon, setHorizon] = useState(10);
  const profile = useMemo(() => turningProfile(instrumentCode), [instrumentCode]);
  const rules = useMemo(() => ({ ...DEFAULT_TURNING_OPTIONS, ...profile.options }), [profile]);
  const input = useMemo(() => history.filter(row => row.date <= end && (!profile.analysisStart || row.date >= profile.analysisStart)), [history, end, profile]);
  const calculation = useMemo(() => calculateTurningPoints(input, rules), [input, rules]);
  const rows = useMemo(() => history.filter(row => row.date >= start && row.date <= end), [history, start, end]);
  const visiblePoints = useMemo(() => calculation.points.filter(point => point.date >= start).map(point => ({
    ...point, signal: point.signal && (point.signal.kind === "bottom" ? showBottom : showTop) ? point.signal : undefined,
  })), [calculation, start, showBottom, showTop]);
  const stats = useMemo(() => evaluateTurningPoints(input, calculation.signals, start, end, horizon), [input, calculation, start, end, horizon]);
  const last = calculation.points.at(-1);
  return <>
    <div className="chart-local-controls turning-controls">
      <label><input type="checkbox" checked={showBottom} onChange={event => setShowBottom(event.target.checked)} /><span className="turning-bottom">▲ 底部确认</span></label>
      <label><input type="checkbox" checked={showTop} onChange={event => setShowTop(event.target.checked)} /><span className="turning-top">▼ 顶部确认</span></label>
      {controls}
    </div>
    <KLine rows={rows} historyRows={input} theme={theme} trades={trades} turningPoints={visiblePoints} />
    {profile.analysisStart && end < profile.analysisStart ? <p className="notice warning">顶底指标：该区间早于最近份额折算后的计算起点 {profile.analysisStart}，不产生确认。</p>
      : (last?.state === "数据预热" || last?.state === "行情无效") && <p className="notice warning">顶底指标：{last.state === "数据预热" ? "连续有效行情不足60条，暂不能确认顶底。" : "末日行情无效，暂停确认并重新预热。"}</p>}
    <details className="research-evidence turning-evaluation">
      <summary>顶底指标 · 规则与历史检验（实验）</summary>
      <p>分类：{profile.name} · 跟踪指数：{profile.index} · 参数来自50轮历史拟合，本次未达80%验证目标 · 区间末日：{last?.state ?? "无数据"} · 数据截止：{input.at(-1)?.date ?? "—"} · 规则版本：{TURNING_VERSION} · 来源：本地财通证券日行情</p>
      <label className="turning-horizon">确认后观察期<select value={horizon} onChange={event => setHorizon(Number(event.target.value))}>
        {[5, 10, 20].map(days => <option key={days} value={days}>{days} 个交易日</option>)}
      </select></label>
      <div className="turning-statistics">
        {(["bottom", "top"] as const).map(kind => {
          const value = stats[kind];
          return <section key={kind} aria-label={`${kind === "bottom" ? "底部" : "顶部"}确认历史检验`}>
            <h3>{kind === "bottom" ? "底部确认" : "顶部确认"}</h3>
            <dl className="readout-values">
              <div><dt>方向命中率</dt><dd>{percent(value.evaluated ? value.hits / value.evaluated : null)}</dd></div>
              <div><dt>命中 / 有效样本</dt><dd>{value.hits} / {value.evaluated}</dd></div>
              <div><dt>待观察 / 断档不可评估</dt><dd>{value.pending} / {value.unavailable}</dd></div>
              <div><dt>平均价格涨跌幅</dt><dd>{percent(value.meanReturn)}</dd></div>
              <div><dt>未筛选日期{kind === "bottom" ? "上涨" : "下跌"}比例</dt><dd>{percent(value.baselineRate)}</dd></div>
            </dl>
            {!value.total && <p>所选日期区间没有{kind === "bottom" ? "底部" : "顶部"}确认。</p>}
          </section>;
        })}
      </div>
      <p>仅统计 {start} 至 {end} 的确认；观察期不越过截止日。底部命中：第{horizon}个交易日收盘高于确认收盘；顶部命中：低于确认收盘。持平算未命中，观察期不足不进入分母；开关和图内缩放不改变统计。</p>
      <p>斜率：对数收盘价5／20／60日线性回归，以ATR14／收盘价归一化。20日斜率连续{rules.backgroundDays}日达到±{rules.slopeThreshold}建立观察背景；底部按{rules.breakoutWindow}日结构、{rules.confirmationDays + 1}日确认及MA{rules.confirmationMaWindow}判断，顶部按{rules.topBreakoutWindow ?? rules.breakoutWindow}日结构、{(rules.topConfirmationDays ?? rules.confirmationDays) + 1}日确认及MA{rules.topMaWindow ?? rules.confirmationMaWindow}判断{rules.topTrailingAtr ? `，另启用底部后高点回落${rules.topTrailingAtr}ATR且短斜率转负的顶部确认` : ""}。触发依据以图上具体信号为准。</p>
      <p>标记在确认日收盘后出现，不回填最低／最高日；后续失效仍保留。悬停或键盘日期读数可查看状态、斜率、触发依据和失效参考价。历史至少预热60条；坏行情或超过15日断档重新预热。159922、159977、510310从最近份额折算后的首个交易日开始计算，折算前K线仍展示但不参与指标；图表交易日按本地记录计。</p>
      <p>分类参数用当前冻结历史寻优，样本并非独立验证；近期走势曾参与观察，不是样本外结果。方向检验不计费用，分红、折算、缺失和源修订会影响结果，不代表真实顶底、未来正确率或买卖指令。</p>
    </details>
  </>;
}
