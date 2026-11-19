import type { JourneyCatalog, TemplateDefinition } from "../lib/strategyJourney";
import { journeyUrl } from "../lib/strategyJourney";

type Props = {
  template: TemplateDefinition;
  templates: JourneyCatalog["templates"];
  code: string;
};

const indicators = [
  ["含息价格序列", "以前一交易日指数乘以（当日收盘价＋当日现金分红）／前一日收盘价逐日更新。", "尽量把现金分红计入趋势观察，算法不直接用未经调整的收盘价判断长期涨跌。"],
  ["均线偏离", "当前含息价格指数／过去 N 个交易日含息指数均值－1。常用 N 为 5、10、20、60。", "正值表示价格在均线上方，负值表示在均线下方；慢周期用于过滤逆势买入。"],
  ["RSI", "14 日上涨幅度总和／（上涨幅度总和＋下跌幅度总和）×100；采用简单窗口，不作 Wilder 平滑。无涨跌时取 50。", "低于 35 表示近期下跌占优并进入超卖观察区；高于 70 表示近期上涨占优，仍需动量转弱才构成卖出风险票。"],
  ["动量", "当前含息价格指数／N 个交易日前含息价格指数－1。入场修复使用 3 日动量，退出确认使用 1 日和 3 日动量。", "正的 3 日动量代表短线价格开始修复；负动量用于确认趋势转弱或超买后的回落。"],
  ["成交量比", "当日原始成交量／此前 20 个交易日成交量均值；均值不包含当日。", "量比衡量突破或修复是否得到交易活跃度支持。箱体突破要求至少 1.2，其余算法要求至少 0.8。"],
  ["区间突破", "当日含息收盘指数高于此前 N 个交易日含息收盘指数最高值；比较窗口不包含当日。", "价格离开近期收盘区间，可能表示供需平衡被打破；量能与趋势条件用于减少单日噪声。"],
  ["顶底确认事件", "先观察过去 20 日对数价格斜率相对 ATR 的标准化方向；连续 3 日达到 ±0.05 后，等待 5 日斜率反转、长斜率改善和价格/20 日均线确认。随后要求价格突破此前 10 日高点或低点至少 0.2 ATR，并再经过至少 1 日确认。", "事件记录的是确认日，不是事后最低点或最高点。底部和顶部交替确认，事件供买入结构或卖出风险投票使用。"],
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

export default function AlgorithmGuide({ template, templates, code }: Props) {
  const guide = guides[template.id];
  if (!guide) return <p className="notice warning">这套算法尚无详细说明。</p>;

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
        <tbody>{indicators.map(([name, formula, meaning]) => <tr key={name}><th scope="row">{name}</th><td data-label="计算口径">{formula}</td><td data-label="市场解释">{meaning}</td></tr>)}</tbody>
      </table></div>
    </section>

    <section>
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
    </section>

    <section>
      <h3>计算与交易口径</h3>
      <ul>
        <li>按交易日期正序逐日计算，只读取当日及此前数据；顶底事件在确认日生成。</li>
        <li>至少预热 60 个交易日；收盘产生目标，下一交易日开盘模拟执行。</li>
        <li>比较默认本金 50,000 元、佣金万分之一、最低佣金 0 元、滑点 5 基点，按 100 份整手交易。</li>
        <li>已核实现金分红计入价格序列与持仓权益；当前三套共享算法不使用 PE/PB 或恐贪指标。</li>
        <li>完整平仓轮次才进入胜率分母，区间结束仍持有的轮次单独列示。</li>
      </ul>
      <p>历史比较保留计算时的内部规则快照供复核；本页解释当前代码中的现行规则。{guide.commonNote}</p>
    </section>

    <section>
      <h3>迭代与复核</h3>
      <p>每次调整先指出希望解决的具体失效场景，再对照逐笔入场、退出原因与日 K 检查：调整是否减少该类错误、是否引入漏信号或更差的回撤。</p>
      <p>同一区间用于观察变化，不用于证明泛化。还应在未参与调整的后续区间及不同 ETF 上复测，并同时看完成轮次数、胜率、收益、最大回撤、在场时间和未平仓数量。</p>
      <p>胜率只统计完整平仓轮次；样本少时波动很大。80% 是研究目标，不是该算法对未来行情的保证。</p>
    </section>
  </article>;
}
