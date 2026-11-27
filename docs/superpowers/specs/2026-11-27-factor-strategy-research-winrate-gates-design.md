# 分类因子策略研究规则与门禁设计（胜率导向版）

**版本：** `factor-strategy-research-v1.2.0`
**状态：** 规则、冻结适配与单元测试已实现；50 轮离线筛选待按本规范独立执行，不自动发布策略。

## 核心调整

将分类因子策略研究从“追求跑赢一直持有”调整为**“以胜率 + 正期望 + 利润因子 + 回撤为门禁，一直持有仅作为对比参照项”**，并配合已补齐的 `2019-01-01` 起长周期数据，收紧防止表达式退化成全天候持仓或架空退出的反作弊约束。

## 一、 样本数据与窗口切分规则

1. **研究起点与真实停牌日放行**
   - `scripts/freeze_factor_strategy_research.py` 默认从 `2019-01-01` 起冻结本地已核验行情、权益与指数映射（晚于 2019 年上市的标的从上市首日起）。
   - 对于经 `.local/free-history-verification.json` 跨源比对确认在所有可用免费源中均无交易的真实停牌日（如折算停牌日），由 `factor_strategy_snapshot.py` 明确核验后放行并登记在 `coverage.verified_suspensions`；任何未核验缺日仍拒绝冻结。
2. **留出切分与跨边界归因**
   - 当冻结池存在多年度样本（`>= 500` 根交易日）时，`holdout_start_date` 按多年度标的的中位有效长度取最后 `20%` 作为共同留出段（约 `337` 个交易日），不再被 2025 年上市的次新 ETF 拖短为 60 天。
   - 仅在开发段具备有效交易窗口的标的纳入该类别的留出与压力成本评估。
   - 留出段延续连续账户净值曲线，不强平或重置现金；交易层 `completed`、`win_rate`、`expectancy` 和 `profit_factor` 只统计留出期内新开且平仓的轮次，跨边界持仓单独计数。

## 二、 因子、成本与风控不变边界

- 只使用 `research_factors.py` 中 11 个既有因子，不改动指标公式或因子阈值。
- 统一 50,000 元研究本金、整手、次日开盘成交及已核实现金分红；普通成本（万一免零 + 5bp 滑点）与压力成本（万三最低 5 元 + 10bp 滑点）。
- 统一风控基线（不参与搜索）：`warmup=65`，初始止损 `min(7%, 2.0 × ATR)`，盈利 `2.5 × ATR` 启动单调 `2.5 × ATR` 移动保护，盈利 `5.0 × ATR` 收紧至 `1.8 × ATR`，持仓满 `18` 个交易日且浮盈不足 `1.0 × ATR` 时间退出。

## 三、 表达式与三条反作弊规则

在布尔化简和中文说明 $\le 100$ 字符的基础上，增加三条结构约束：

1. **禁止入场表达式顶层为 `NOT`**：防止 `非（罕见组合）` 变成高暴露伪满仓。
2. **禁止对离散 `event` 因子直接套 `consecutive`**：`turning_bottom`、`turning_top`、`ma5_cross_ma20_up`、`box_breakout_up`、`volume_breakout_up`、`oversold_recovery`、`strong_close`、`atr_box_breakout` 仅允许单日触发，防止 `连续5日满足阶段顶部确认` 架空因子退出；仅 `state` 型状态因子（`atr_oversold`、`wilder_rsi_oversold`、`ma60_rising`）允许 `consecutive`。
3. **禁止 `within` / `consecutive` 直接嵌套**：避免多层时间算子套娃降低可审查性。

## 四、 门禁、评分与对比参照

- **硬性淘汰门禁（开发与留出均须满足）**：
  - `completed >= 5`
  - `win_rate >= 65%`
  - `expectancy > 0`
  - `profit_factor >= 1.25`
  - `return > 0`
  - `drawdown >= -12%`
  - `independent_units >= 2` 且至少 `50%` 独立单位同时满足 `return > 0`、`expectancy > 0` 与 `win_rate >= 65%`（单独立单位类别始终标为“单标的证据”，不能发布）
- **演化评分目标（仅看开发段）**：
  - `completed < 5`、`expectancy <= 0` 或 `profit_factor < 1.0` 时得分为 `0.0`；
  - 以 `win_rate` 为核心权重，结合封顶 `4.0` 的 `profit_factor`、归一化 `expectancy`、绝对收益与回撤惩罚，乘以样本权重（向 `20` 笔爬坡）与达标单位占比；
  - **不再将 `excess_return`（跑赢一直持有）作为评分或门禁项**。
- **对比参照项（只展示不否决）**：
  - 同成本一直持有收益（`benchmark_return`）、回撤（`benchmark_drawdown`）、相对超额（`excess_return`）、在场暴露率（`exposure`）、暴露调整收益（`exposure_adjusted_return`）与熊市防守捕获指标。
