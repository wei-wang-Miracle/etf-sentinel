import type { JourneyCatalog, TemplateDefinition, TemplateRule, TurningProfile } from "../lib/strategyJourney";
import { journeyUrl } from "../lib/strategyJourney";

type Props = {
  template: TemplateDefinition;
  templates: JourneyCatalog["templates"];
  instruments: JourneyCatalog["instruments"];
  code: string;
  onCode: (code: string) => void;
};

const indicators = [
  ["含息价格序列", "以前一交易日指数乘以（当日收盘价＋当日现金分红）／前一日收盘价逐日更新。", "尽量把现金分红计入趋势观察，算法不直接用未经调整的收盘价判断长期涨跌。"],
  ["均线偏离", "当前含息价格指数／过去 N 个交易日含息指数均值－1。常用 N 为 5、10、20、60。", "正值表示价格在均线上方，负值表示在均线下方；慢周期用于过滤逆势买入。"],
  ["RSI", "14 日上涨幅度总和／（上涨幅度总和＋下跌幅度总和）×100；采用简单窗口，不作 Wilder 平滑。无涨跌时取 50。", "低于 35 表示近期下跌占优并进入超卖观察区；高于 70 表示近期上涨占优，仍需动量转弱才构成卖出风险票。"],
  ["动量", "当前含息价格指数／N 个交易日前含息价格指数－1。入场修复使用 3 日动量，退出确认使用 1 日和 3 日动量。", "正的 3 日动量代表短线价格开始修复；负动量用于确认趋势转弱或超买后的回落。"],
  ["成交量比", "当日原始成交量／此前 20 个交易日成交量均值；均值不包含当日。", "量比衡量突破或修复是否得到交易活跃度支持。箱体突破要求至少 1.2，其余算法要求至少 0.8。"],
  ["区间突破", "当日含息收盘指数高于此前 N 个交易日含息收盘指数最高值；比较窗口不包含当日。", "价格离开近期收盘区间，可能表示供需平衡被打破；量能与趋势条件用于减少单日噪声。"],
  ["顶底确认事件", "服务端以含息OHLC计算5／20／60日对数收盘价斜率，并以ATR14／收盘价归一化；统一状态机按趋势背景、短斜率、均线、区间突破、确认等待、冷却与底顶交替生成事件。", "事件记录的是确认日，不是事后最低点或最高点。ETF只能调整该因子的固定参数模板，不能改写指标公式、确认顺序或因果边界。"],
];

const guides: Record<string, { structure: string; marketMeaning: string; commonNote: string }> = {
  range_breakout: {
    structure: "当日含息收盘指数高于此前 20 个交易日的最高收盘指数。",
    marketMeaning: "定位近期收盘区间向上扩张，并要求 60 日趋势不弱、3 日动量转正以及成交量比达到 1.2。它偏向确认趋势延续，不尝试抄到最低价。",
    commonNote: "主要检查假突破、放量后的回落，以及突破发生时 60 日趋势是否真的改善。",
  },
  bottom_confirmation: {
    structure: "最近 5 个交易日内出现一次因果确认的底部事件。",
    marketMeaning: "先确认此前存在持续下行背景，再等短斜率转正、长斜率改善、价格站回上行的 20 日均线并完成区间突破。信号出现在反转证据形成后，不等于市场最低点。",
    commonNote: "主要检查下跌趋势中短暂反弹造成的误确认，以及结构确认后继续破位的场景。",
  },
  hybrid_reversal: {
    structure: "最近 5 日内出现底部确认事件，或 RSI14 不高于 35，或价格低于 20 日均线至少 2%；三者任一成立即可进入其他条件核验。",
    marketMeaning: "把趋势反转、短期超卖和均线回落作为互补的候选结构，再要求修复、慢趋势和量能多数通过。它覆盖面更广，但结构触发本身不是买入信号。",
    commonNote: "应分别统计底部事件、超卖和均线回落三类结构的后续表现，判断贡献来自哪里，避免只看汇总胜率。",
  },
};

function MultifactorRules({ rule }: { rule: TemplateRule }) {
  const percent = (value: TemplateRule[string]) => `${(Number(value) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
  const bottom = `最近 ${rule.event_age} 个交易日内出现底部确认（含当日）`;
  const oversold = `RSI${rule.rsi_window} 不高于 ${rule.rsi_buy}，或含息收盘的 MA20 偏离不高于 ${percent(-Number(rule.dip))}`;
  const structures: Record<string, string> = {
    breakout: `当日含息收盘指数高于此前 ${rule.break_window} 个交易日的最高含息收盘指数`,
    bottom,
    hybrid: `${bottom}，或${oversold}`,
    oversold,
    pullback: `含息收盘的 MA${rule.fast} 偏离不高于 ${percent(-Number(rule.dip))}`,
  };
  const valuation = rule.value_metric === "pe_percentile" ? "PE" : "PB";
  const hasValuation = rule.value_metric !== "none";
  return <>
    <p><strong>入场结构：</strong>{structures[String(rule.family)]}。</p>
    <p><strong>买入：</strong>入场结构必须通过。{rule.recovery} 日动量大于零、{rule.slow} 日均线偏离不低于 {percent(rule.trend_floor)}、量比不低于 {rule.volume_min} 各计一票，加上结构{hasValuation ? "和估值" : ""}，至少需要 {rule.buy_votes} 票。</p>
    <p>{hasValuation ? `还必须取得前一 ETF 交易日的关联指数 ${valuation} 分位，且数值不高于 ${rule.value_max}。分位按截至源日的十日历年有效估值计算，缺失时禁止新开仓。` : "该 ETF 的规则不使用估值过滤。"}</p>
    <p><strong>卖出风险：</strong>最近 {rule.event_age} 个交易日内出现顶部确认（含当日）、含息收盘低于 MA{rule.exit_ma} 且 3 日动量为负、RSI{rule.rsi_window} 不低于 {rule.rsi_sell} 且 1 日动量为负，各计一票。达到 {rule.sell_votes} 票触发退出，也阻止当日新开仓。</p>
    <p><strong>持仓约束：</strong>收益率不高于 {percent(-Number(rule.stop_loss))}、达到 +{percent(rule.take_profit)}、较持仓收益率峰值回落至少 {Number(rule.trailing) * 100} 个百分点，或持有满 {rule.max_holding} 个交易日，任一条件触发退出。距卖出成交日的交易日数须大于 {rule.cooldown} 才能再次发出买入信号。</p>
  </>;
}

function TurningProfileRules({ profile }: { profile: TurningProfile }) {
  const parameters = profile.parameters;
  const topTrailing = parameters.top_trailing_atr > 0
    ? `；顶部另在底部确认后，高点回落至少 ${parameters.top_trailing_atr} ATR 且短斜率转负时确认`
    : "";
  return <>
    <p><strong>当前 ETF 顶底参数模板：</strong>{profile.group_name}。该模板与其他 ETF 共用同一因果事件引擎。</p>
    <p><strong>趋势与底部：</strong>20日斜率连续 {parameters.background_days} 日达到 ±{parameters.slope_threshold} 建立背景；底部以 {parameters.breakout_window} 日结构、MA{parameters.confirmation_ma_window}、至少 {parameters.confirmation_days + 1} 日确认、{parameters.breakout_atr_multiplier} ATR 突破倍数和 {parameters.cooldown_days} 日冷却期判断。</p>
    <p><strong>顶部：</strong>使用 {parameters.top_breakout_window} 日结构、MA{parameters.top_ma_window} 与至少 {parameters.top_confirmation_days + 1} 日确认{topTrailing}。</p>
  </>;
}

export default function AlgorithmGuide({ template, templates, instruments, code, onCode }: Props) {
  const guide = guides[template.id];
  const multifactor = template.rules_by_instrument;
  const turningProfile = template.turning_profiles_by_instrument?.[code];
  if (!guide && !multifactor) return <p className="notice warning">这套算法尚无详细说明。</p>;
  const definitions = multifactor ? indicators.map(([name, formula, meaning]) => {
    if (name === "均线偏离") return [name, "当前含息价格指数／过去 N 个交易日含息指数均值－1。窗口按 ETF 研究规则选取。", meaning];
    if (name === "RSI") return [name, "N 日上涨幅度总和／（上涨幅度总和＋下跌幅度总和）×100。采用简单窗口，无涨跌时取 50。", "低位用于识别超卖，高位配合负动量用于识别上冲后转弱。窗口和门槛按 ETF 规则选取。"];
    if (name === "动量") return [name, "当前含息价格指数／N 个交易日前含息价格指数－1。入场窗口按 ETF 规则选取，卖出风险使用 1 日和 3 日动量。", "正动量表示价格开始修复，负动量用于核验趋势转弱或超买后的回落。"];
    if (name === "成交量比") return [name, formula, "用于判断突破或修复是否得到交易活跃度支持，门槛按 ETF 规则选取。"];
    return [name, formula, meaning];
  }).concat([["指数估值分位", "用前一 ETF 交易日的关联指数估值，统计截至源日的十日历年有效估值中严格低于该值的比例。PE 和 PB 只使用正值。", "部分 ETF 用于过滤相对估值过高的入场机会。"]]) : indicators;

  return <article className="algorithm-guide">
    <header className="algorithm-guide-header">
      <div>
        <h2>{template.name}算法说明</h2>
        <p>{template.description}</p>
      </div>
      <a className="button-link" href={journeyUrl("strategies", code || undefined, { view: "backtest", algorithm: template.id })}>回测这套算法</a>
    </header>
    <nav className="algorithm-guide-nav" aria-label="切换算法说明">
      {templates.map((item) => <a key={item.id} aria-current={item.id === template.id ? "page" : undefined}
        href={journeyUrl("strategies", code || undefined, { view: "algorithm", algorithm: item.id })}>{item.name}</a>)}
    </nav>

    <section>
      <h3>指标定义与市场含义</h3>
      <div className="algorithm-guide-table" role="region" aria-label="算法指标定义与市场含义" tabIndex={0}><table>
        <thead><tr><th scope="col">指标</th><th scope="col">计算口径</th><th scope="col">市场解释</th></tr></thead>
        <tbody>{definitions.map(([name, formula, meaning]) => <tr key={name}><th scope="row">{name}</th><td data-label="计算口径">{formula}</td><td data-label="市场解释">{meaning}</td></tr>)}</tbody>
      </table></div>
    </section>

    <section>
      <h3>统一顶底确认因子</h3>
      {turningProfile ? <TurningProfileRules profile={turningProfile} /> : <p>当前标的尚无顶底参数模板。该算法的事件口径仍只由服务端统一引擎生成。</p>}
    </section>

    {multifactor ? <section>
      <h3>逐 ETF 买入与退出规则</h3>
      <p>沿用 50 轮研究最终为每只 ETF 选出的规则。同一跟踪指数下，不同 ETF 也可能采用不同入场结构和阈值。</p>
      <label className="object-selector">查看 ETF 规则<select value={multifactor[code] ? code : ""} onChange={(event) => onCode(event.target.value)}>
        <option value="">选择 ETF</option>
        {instruments.filter((item) => multifactor[item.instrument_code]).map((item) => <option key={item.instrument_code} value={item.instrument_code}>{item.instrument_code} · {item.instrument_name}</option>)}
      </select></label>
      {multifactor[code] && <MultifactorRules rule={multifactor[code]} />}
    </section> : guide && <><section>
      <h3>入场结构</h3>
      <p><strong>{template.name}：</strong>{guide.structure}</p>
      <p>{guide.marketMeaning}</p>
    </section>

    <section>
      <h3>买入与退出规则</h3>
      <p>买入结构必须成立，四项核心条件至少满足三项。</p>
      <ul>
        <li>结构：使用本算法对应的入场结构。</li>
        <li>修复：3 日动量大于 0。</li>
        <li>趋势：60 日均线偏离不低于 -3%；箱体突破要求不低于 0%。</li>
        <li>量能：箱体突破的成交量比至少 1.2；底部确认与复合反转至少 0.8。</li>
      </ul>
      <p>即使入场票数足够，退出风险票达到 2 项时也不新开仓；退出后至少经过 3 个交易日才允许再次买入。</p>
      <p>卖出风险来自三项：最近 5 日内出现顶部确认；收盘低于 10 日均线且 3 日动量为负；RSI14 不低于 70 且 1 日动量为负。达到任意两项时触发风险退出。</p>
      <p>持仓还受止损 -5%、止盈 +7%、从持仓期峰值回撤 5%、最长持有 30 个交易日约束；任一约束触发即产生卖出目标。</p>
    </section></>}

    <section>
      <h3>计算与交易口径</h3>
      <ul>
        <li>按交易日期正序逐日计算，只读取当日及此前数据；顶底事件在确认日生成。</li>
        <li>{multifactor ? "最早在第 61 个交易日收盘判断，长窗口需要更多预热。" : "至少预热 60 个交易日。"}收盘产生目标，下一交易日开盘模拟执行。</li>
        <li>比较默认本金 50,000 元、佣金万分之一、最低佣金 0 元、滑点 5 基点，按 100 份整手交易。</li>
        <li>已核实现金分红计入价格序列与持仓权益。{multifactor ? "估值使用可能经源修订的历史序列。" : "当前三套共享算法不使用 PE/PB 或恐贪指标。"}</li>
        <li>完整平仓轮次才进入胜率分母，区间结束仍持有的轮次单独列示。</li>
      </ul>
      <p>历史比较保留计算时的内部规则快照供复核。本页解释当前代码中的现行规则。{guide?.commonNote}</p>
    </section>

    <section>
      <h3>迭代与复核</h3>
      {multifactor && <p>50 轮研究在参与选参的历史中取得 166 胜／187 笔（88.8%）。最近一段已观察区间以空仓重算为 27 胜／42 笔（64.3%）。</p>}
      <p>每次调整先指出希望解决的具体失效场景，再对照逐笔入场、退出原因与日 K 检查：调整是否减少该类错误、是否引入漏信号或更差的回撤。</p>
      <p>同一区间用于观察变化，不用于证明泛化。还应在未参与调整的后续区间及不同 ETF 上复测，并同时看完成轮次数、胜率、收益、最大回撤、在场时间和未平仓数量。</p>
      <p>胜率只统计完整平仓轮次；样本少时波动很大。80% 是研究目标，不是该算法对未来行情的保证。</p>
    </section>
  </article>;
}
