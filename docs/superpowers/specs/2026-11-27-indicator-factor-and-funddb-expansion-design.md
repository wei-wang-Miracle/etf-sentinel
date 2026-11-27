# 指标因子扩展与 FundDB 新数据源接入设计方案

**状态：** 已确认待实现（设计规格，供工程代理按三阶段独立落地）
**主归属与协作域：**
- 阶段一（既有数据盘活与技术因子扩展）：主归属 `策略研究`，协作 `投研分析`
- 阶段二（全市场恐贪与五维 Regime 子因子接入）：主归属 `数据基础`，协作 `投研分析`、`策略研究`
- 阶段三（场内 ETF 截面档案、指数映射辅助与日度份额流）：主归属 `数据基础`，协作 `投研分析`

本文档整合当前 `etf-sentinel` 指标因子层盘点与对 `funddb.cn`（`ai2.jiucaishuo.com/api` / `config.jiucaishuo.com`）实测抓包结论，给出数据库、后端采集与计算接口、前后端交互及验收标准的完整落地设计。

---

## 0. 设计原则与全局边界（实现必读）

任何阶段的实现均须严格遵守 [AGENTS.md](../../../AGENTS.md)、[数据库说明](../../database.md) 与 [设计契约](../../design-contract.md) 中的工程底线：

1. **严禁未来函数与历史伪造**：
   - 外部源接口只覆盖近 1 年或当日截面的数据（如 `fear-greed` 五维子因子、`fundsale/etf` 实时/T-1 截面），**只能按运行日逐步落库积累**，严禁推断或补写未返回的历史日期。
   - 外部日频指标进入单 ETF 日频策略或因子真值计算时，必须满足**严格早于 ETF 交易日（`source_date < etf_trade_date`）**，并与本地 `collected_at` 共同记录可用覆盖区间；缺日与无映射保持 `available=False`，不得当作看空/看多或补零。
   - 明确**禁止接入日频回测信号**的接口：`fund/scale-change`（季报/中报存在数周至数月披露滞后，直接对齐报告期即未来函数）、`fund/invest/fg` 与 `invest/cg`（季报拟合/前十大持仓）、`fund/ttm`（盘中实时关联板块涨跌）。
2. **业务实体与接口规范**：
   - 指标与因子计算逻辑只在 Python 代码实现；数据库 `research_factors` 仅登记因子身份、名称、分类、输出类型（`event`/`state`）和含义，不入库可执行表达式。
   - 所有新增业务表与字段须在 SQLAlchemy 模型与 Alembic 迁移中提供详尽中文 `COMMENT`（含单位、时区、取值范围、可空含义、数据源口径）。
   - 不主动接入账户交易、自动下单、盘中实时行情或新通知渠道。
3. **视觉与交互契约**：
   - 沿用“我的 ETF / 我的策略 / 数据管理”三个主导航，不新增一级导航入口。
   - 严格隔离三套颜色语义：红涨绿跌（仅行情与收益率）、蓝恐惧/琥珀贪婪（仅情绪）、成功/告警/危险系统色（任务与校验），`primary` 朱红操作强调色不用于数值涨跌或情绪。
   - 数值、代码、日期统一等宽字体（`.mono` / `tabular-nums`）；每个数据视图完整覆盖加载、空态、错误重试与缺失原因说明。

---

## 1. 阶段一：盘活已入库估值指标与扩展技术因子（零新外部依赖）

### 1.1 解决的问题与现有模块关系

当前 [index_valuation.py](../../../api/app/index_valuation.py) 已采集 8 个关联指数的 5 类日频估值（`METRICS = {"pe", "pb", "xilv", "roe", "premium_diff"}`），但 [research_factor_context.py](../../../api/app/research_factor_context.py) 的 `_valuation_changes` 仅消费了 `pe` 与 `pb`，导致**股息率（`xilv`）、净资产收益率（`roe`）与股债风险溢价（`premium_diff`）未进入因子目录与离线策略研究**。

同时，[indicators.py](../../../api/app/indicators.py) 与 [research_factors.py](../../../api/app/research_factors.py) 当前最长均线仅到 `MA60`，缺少**长期趋势锚（`MA120`/`MA250`）、趋势强度（ADX14）、回撤深度、相对基准强弱与连续结构**，难以过滤高波动熊市逆风交易以稳定达成 `v1.2.0` 胜率门禁（胜率 ≥ 65%、PF ≥ 1.25、最大回撤 ≥ -12%）。

### 1.2 指标算子扩展（`api/app/indicators.py`）

在保留现有 `prior_close_margin`、`volume_ratio`、`wilder14` 的基础上，新增以下纯函数算子（均使用含息序列，严禁跨日未来访问）：

| 函数签名（建议） | 计算口径 | 返回类型 |
| :--- | :--- | :--- |
| `rolling_sma(values, index, window)` | 取 `values[index - window + 1 : index + 1]` 算术均值；`index + 1 < window` 返回 `None` | `float \| None` |
| `wilder_adx14(prev_high, prev_low, prev_close, high, low, close, index, state)` | 标准 14 日 Wilder `+DI`、`-DI`、`DX` 与 `ADX14` 平滑状态机；前 28 根预热期 `adx` 为 `None` | `tuple[float \| None, float \| None, float \| None, dict]` |
| `drawdown_from_peak(values, index, window)` | `values[index] / max(values[max(0, index - window + 1) : index + 1]) - 1`，返回 `<= 0` 小数 | `float \| None` |
| `consecutive_down_count(values, index)` | 自 `index` 向前连续满足 `values[k] < values[k - 1]` 的交易日天数（`index == 0` 返回 `0`） | `int` |
| `excess_return(values, bench_values, index, window)` | ETF 与基准（同日对齐序列）过去 `window` 日收益率差值；任一方预热不足返回 `None` | `float \| None` |

### 1.3 外部估值因子扩展（`api/app/research_factor_context.py`）

在 `build_external_factor_truth()` 中扩展 `_valuation_changes()`：

* **`xilv`（股息率）**：仅采纳 `value_status == "valid"`（遵循 [index_valuation.py](../../../api/app/index_valuation.py)，股息率 `0` 为有效值，`not_applicable` 不入统计），经 `rolling_percentiles` 计算截至当日的十日历年本地回看分位。
* **`premium_diff`（股债风险溢价）**：允许正负实数（`value_status == "valid"` 即入统计），经 `rolling_percentiles` 计算截至当日的十日历年本地回看分位。
* **`roe`（净资产收益率）**：入库单位统一为百分数，允许负值（`value_status == "valid"`），计算本地回看分位用于基本面强弱过滤。
* **因果对齐与缺日规则**：继续保持 `valuation_days[valuation_cursor] < day` 推进游标，严格早于 ETF 交易日，不将 `not_applicable` 或缺失写成 `True`。

### 1.4 新增原子因子目录（`api/app/research_factors.py` + Alembic 迁移）

通过新增 Alembic 迁移向 `research_factors` 插入以下原子因子（所有阈值常量写入 `research_factors.py` 顶部，不开放用户编辑；`chart_visible` 按观察可读性设定）：

| `factor_id` | 中文名称 | `category` | `output_type` | 触发/状态判定口径 | `chart_visible` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `erp_high_percentile` | 股债高性价比保护 | `外部估值` | `state` | 关联指数此前最近可得 `premium_diff` 本地十年分位 `>= 70%` | `true` |
| `erp_low_percentile` | 股债性价比偏低 | `外部估值` | `state` | 关联指数此前最近可得 `premium_diff` 本地十年分位 `<= 20%` | `true` |
| `dividend_yield_high` | 高股息率保护 | `外部估值` | `state` | 关联指数此前最近可得 `xilv` 本地十年分位 `>= 70%` | `true` |
| `above_ma250` | 年线多头区间 | `趋势状态` | `state` | 含息收盘价严格高于 `MA250`（预热不少于 250 日） | `true` |
| `ma120_rising` | 半年线向上 | `趋势状态` | `state` | `MA120` 严格高于 5 个交易日前（预热不少于 125 日） | `false` |
| `adx_trending` | 趋势形成状态 | `趋势状态` | `state` | `ADX14 >= 25` 且 `+DI14 > -DI14`（区分单边上行与震荡） | `false` |
| `adx_choppy` | 无趋势震荡状态 | `趋势状态` | `state` | `ADX14 < 18` | `false` |
| `deep_drawdown_60d` | 60日深度回撤状态 | `超跌状态` | `state` | 含息收盘较过去 60 日最高收盘回撤 `<= -10%`（且不超过 `-35%` 异常值） | `true` |
| `consecutive_down_exhaustion` | 连跌耗竭观察 | `超跌状态` | `state` | 含息收盘连续下跌不少于 `4` 个交易日 | `true` |
| `gap_up_strong` | 强势跳空高开 | `突破确认` | `event` | 当日低点高于前一日高点至少 `0.3 * ATR14`，且收盘位于振幅上半区 | `true` |
| `relative_strength_20d_positive` | 相对沪深300跑赢 | `相对强弱` | `state` | 若存在基准 `000300.SH` 指数日K因果对齐序列，ETF 20日含息收益跑赢基准 `>= 1.5%` | `false` |

> **说明**：`relative_strength_20d_positive` 依赖本地 `index_candles` 中的 `000300.SH` 历史序列（严格 `index_trade_date <= etf_trade_date` 同期闭合收益，盘前策略/回测时用当日收盘对齐；若本地缺少 `000300.SH` 序列则该因子恒为 `False` 并在 `external_factor_context` 标注原因）。

### 1.5 后端 API 与前端交互改动（阶段一）

* **后端兼容检查**：
  - `GET /factors`（[main.py](../../../api/app/main.py#L289)）自动返回新入库因子及分类；
  - `GET /candles/{code}/factors`（[main.py](../../../api/app/main.py#L315)）同步查询 `000300.SH` 基准序列（若有）和全部 5 类估值指标传入 `build_external_factor_truth`；
  - `factor_strategy_snapshot.py` 与离线筛选器自动接管新增因子进入表达式搜索空间。
* **前端交互优化（[EtfFactorChart.tsx](../../../web/src/components/EtfFactorChart.tsx)）**：
  1. **清理历史残留**：将 `DEFAULT_FACTORS` 中已于迁移 `0019` 移除的 `"oversold_recovery"` 替换为默认展示的原子因子（如 `["turning_bottom", "turning_top", "close_above_prior_high"]`），防止默认计数值虚高或匹配失败。
  2. **因子弹窗分类分组**：随着可见因子数量接近 30 项，在 `factor-popover` 弹窗内将原有平铺复选框改为**按 `category` 分组折叠/分栏列表**（顺序：`结构确认` → `趋势状态`/`趋势转折` → `突破事件`/`突破确认`/`反转确认` → `波动率状态`/`兑现确认` → `外部估值`/`外部情绪`），支持组内全选/清空、悬停或键盘聚焦更新底部 `factor.meaning` 释义面板。
  3. **空/缺失上下文提示**：当用户勾选了 `外部估值` 或 `相对强弱` 因子但当前 ETF 尚未映射指数时，弹窗旁保留轻提示条 `“该 ETF 尚未映射指数，外部估值标记不可用”` 及跳转 `数据管理 → 标的配置` 链接。

---

## 2. 阶段二：接入全市场恐贪与五维 Regime 子因子（`fear-greed`）

### 2.1 已核实外部数据源与字段契约

* **接口地址**：`GET https://ai2.jiucaishuo.com/api/fear-greed`（支持 `?type=all`，实测返回结构一致，无需登录凭据或 ChatBI Token，须设置 `trust_env=False, follow_redirects=False`）。
* **实测响应结构**（2026-11-27 实测验证）：
  - 顶层字段：`date`（最新源日期，如 `"2026-11-27"`）、`value`（总恐贪分 `0~100`）、`desc`（源情绪标签，如 `"恐惧"`）、`changes`（`one_day`/`one_week`/`one_month`/`one_year`）、`deltas`、`has_data`。
  - **`history` 数组**：全市场恐贪总分历史日序列，实测 **1533 条**（`2020-08-03` 至 `2026-11-27`），元素为 `{"date": "YYYY-MM-DD", "value": float}`。
  - **`factors` 数组（5 个全市场子因子）**：每个对象含 `key`、`name`、`analysis`、`series`（实测均为最近 **242 个交易日** `2025-11-28` ~ `2026-11-27`），`series` 单条格式为 `{"date": "YYYY-MM-DD", "value": float, "pct_all": float, "pct_year": float}`：

| `key` | 源 `name` | 业务含义（实测值域示例） | 本系统策略研究价值 |
| :--- | :--- | :--- | :--- |
| `volatility` | `指数波动：50ETF期权波动率` | 原中国波指 iVIX（恐慌指数），如 `18.76` | **极高**：识别高恐慌/低波动区间，过滤假突破与极端尾部风险 |
| `bx` | `避险天堂：股债回报差` | 近20交易日沪深300与国债净价指数回报差（百分点），如 `1.86` | **高**：识别风险偏好切换与股债资金跷跷板 |
| `premium` | `升贴水率：沪深300股指期货升贴水` | 次月合约 10 日均年化升贴水率（%），如 `-14.15` | **高**：衡量机构/对冲端悲观贴水极值 |
| `wz` | `两市成交额` | 全市场成交活跃度及与20日均线偏离分位，如 `2001906.18`（源单位随响应保留注释，不猜测换算） | **中**：避免极端缩量阴跌与过热放量见顶 |
| `strength` | `股价强度：创新高个股数量占比` | 创近一年新高个股全A占比（%），如 `0.14` | **极高**：全市场广度（Breadth）因子，识别普跌 vs 结构牛 |

### 2.2 数据库表设计（Alembic 迁移）

严格遵循“同义同名、详尽中文 COMMENT、不存推断公式”原则，新增两张表并登记 `job_id = 6`：

1. **`market_fear_greed_daily`（全市场恐贪指数日序列）**
   - `trade_date` (`DATE`, PK)：数据源交易日期，按源值保存；不统一截为北京时间昨日。
   - `fear_greed_score` (`Numeric(8, 4)`, NOT NULL)：全市场恐贪总分，闭区间 `0` 至 `100`；`0` 为有效值。
   - `source_label` (`String(32)`, NULL)：源最新快照当日匹配的情绪标签（仅 `trade_date == top.date` 且分数一致时写入，不推断历史标签）。
   - `collected_at` (`DateTime(timezone=True)`, NOT NULL)：本条首次入库或源值修订的带时区本地采集时间；未变化不重写。

2. **`market_regime_factor_daily`（全市场五维温度子因子日序列）**
   - `factor_key` (`String(32)`, PK)：子因子源键：`volatility`、`bx`、`premium`、`wz`、`strength`。
   - `trade_date` (`DATE`, PK)：数据源交易日期。
   - `factor_name` (`String(100)`, NOT NULL)：源中文名称，不自行重命名或猜指标含义。
   - `raw_value` (`Numeric(24, 6)`, NOT NULL)：源原始读数（允许正负实数，如贴水率与股债差为负，具体单位按 `factor_key` 说明在注释注明）。
   - `source_pct_year` (`Numeric(8, 4)`, NULL)：源返回的近一年分位数 `0~100`，仅供对照展示，**不作为历史固定时点分位**。
   - `source_pct_all` (`Numeric(8, 4)`, NULL)：源返回的全历史分位数 `0~100`，仅供对照展示。
   - `collected_at` (`DateTime(timezone=True)`, NOT NULL)：本条首次入库或字段实际发生变更的本地时间。

3. **独立任务登记（`jobs` 表）**
   - 插入 `job_id = 6`：`schedule_enabled = True`、`scheduled_time = '01:15'`（北京时间，错开任务1的 `01:00`、任务2的 `01:10`、任务3的 `01:20`、任务4的 `01:30`）。
   - 互斥锁使用 `pg_try_advisory_lock(LOCK_ID + 5)`，完全复用 [jobs.py](../../../api/app/jobs.py) 线程与中断恢复模型；修改 `jobs.job_id` 与 `runs.job_id` 字段 `COMMENT`。

### 2.3 后端采集、因果校验与策略接入

* **采集模块 `api/app/market_sentiment.py`**：
  - 每次运行拉取 `GET /api/fear-greed`：校验日期合法且不晚于当前北京时间日期、数值为有限定点数、`fear_greed_score` 在 `[0, 100]`、`source_pct_year` / `source_pct_all` 在 `[0, 100]`。
  - **幂等增量与修订保留**：对比本地同主键记录，仅新增或数值/分位发生变化时执行写入或更新 `collected_at`；**严禁覆盖或删除早于源近 242 日窗口之前的本地已积累子因子历史**（随着每日积累，本地子因子序列会不断突破 242 天向长历史延伸）。
  - 单次运行日志写入 `Run.logs`：`scope` 分别记录 `market_fear_greed` 与五个 `factor_key` 的写入条数/修订条数/日期覆盖区间。
* **因果因子真值扩展（`api/app/research_factor_context.py` + `research_factors.py`）**：
  - 全市场恐贪与子因子**无需 ETF 个体映射**，所有 A 股宽基与行业 ETF 共用（跨市场如纯纳指/黄金 ETF 在因子覆盖提示中标明为“A股全市场背景”）。
  - 严格采用 `source_date < etf_trade_date` 对齐，且**仅使用 `raw_value` 或截至当日的本地滚动分位**，不使用源 `pct_all`（避免未来全部历史分布泄漏）：

| 新增因子 `factor_id` | 中文名称 | `category` | `output_type` | 计算口径 |
| :--- | :--- | :--- | :--- | :--- |
| `market_fear_extreme` | 全市场极度恐惧 | `全市场环境` | `state` | 全市场恐贪总分最近可得值 `<= 25`（基于 2020-08 起序列） |
| `market_greed_extreme` | 全市场极度贪婪 | `全市场环境` | `state` | 全市场恐贪总分最近可得值 `>= 75` |
| `market_ivix_high` | 50ETF波指高位 | `全市场环境` | `state` | `volatility` 最近可得值 `>= 22.0` 或（样本 >= 120 日时）本地 252 日分位 `>= 80%` |
| `market_ivix_calm` | 50ETF波指低波平稳 | `全市场环境` | `state` | `volatility` 最近可得值 `<= 16.0` 且非急剧扩张 |
| `market_breadth_weak` | 全A创新高广度极弱 | `全市场环境` | `state` | `strength`（创新高个股占比）`<= 1.0%` |
| `market_futures_deep_discount` | 股指期货深度贴水 | `全市场环境` | `state` | `premium` 年化升贴水率 `<= -10.0%` |

  - **长区间回测边界**：在 `factor_strategy_snapshot.py` 中明确记录 `market_regime` 的 `first_source_date` 与 `last_source_date`；早于 `first_source_date` 的日期标记为 `False` 且不把缺失误计入活跃状态，避免长周期回测污染。
* **新增路由模块 `api/app/market_sentiment_routes.py`**：
  - `GET /market-sentiment/overview`：返回全市场总恐贪最新读数、涨跌变化（1日/1周/1月）及 5 个子因子各自最新值、源日期、本地覆盖起止日与条数。
  - `GET /market-sentiment/series?start=...&end=...`：返回闭区间总恐贪历史序列及五维子因子日序列（缺日不补零）。
  - `GET /market-sentiment/job` / `PUT /market-sentiment/job` / `POST /market-sentiment/job/run`：与现有任务接口形态完全一致。

### 2.4 前端设计与交互（阶段二）

1. **数据管理 → 任务与运行记录（[Jobs.tsx](../../../web/src/pages/Jobs.tsx)）**
   - 顶部任务标签 `tasks` 数组追加第 6 项：`["market-sentiment", "全市场温度"]`（对应接口 `/market-sentiment/job`）。
   - 收起说明 `<details>` 标明：“全市场恐贪总分自 2020-08 起增量核验；五维子因子仅提供近一年滚动窗口，按日逐步落库积累，不删除旧历史。”
2. **我的 ETF → 研究对象 → 市场情绪标签页（[ResearchObject.tsx](../../../web/src/pages/ResearchObject.tsx)）**
   - **背景切换条**：在现有 `tab === "sentiment"` 顶部控制区保留“已映射行业恐贪”下拉选择的同时，增加分段切换按钮 **`行业恐贪` | `全市场温度与波指`**（支持 URL 参数 `sentiment_scope=industry|market` 恢复；即使某 ETF 未映射行业恐贪，也**默认可直接切换到 `全市场温度与波指`**，彻底消除当前空态盲区）。
   - **指标摘要卡（`.research-metrics`）**：
     - 全市场恐贪分（按恐惧蓝 `--sentiment-fear` / 贪婪琥珀 `--sentiment-greed` 着色 + 文字标签）、50ETF 期权波指 iVIX（等宽数字）、沪深 300 股指期货年化升贴水、创新高个股占比、股债回报差。
   - **主图表区（复用/扩展 `SentimentTrend` 与 `ResearchChart`）**：
     - 主图展示全市场恐贪总分（`0–100` 连续蓝灰琥珀着色，左轴）与 50ETF 波指 iVIX（右轴紫色/青色虚线，使用 `--chart-2` / `--chart-3`，严禁使用红绿）；
     - 下方增加紧凑单子因子切卡（`iVIX波动率` / `股债回报差` / `期指升贴水` / `两市成交额` / `创新高占比`），点击切换下方辅助折线，明确标注“子因子自 `first_source_date` 起本地累积，早于该日无数据不补零”。
3. **横向对比 → 市场情绪背景（[Compare.tsx](../../../web/src/pages/Compare.tsx)）**
   - 当 `dimension === "sentiment"` 时，在对比主图上方新增一行紧凑的「全市场温度与 iVIX 背景条」（卡片式 4 项关键读数 + 跳转到当前 ETF 市场情绪全图链接），使跨行业/跨宽基对比同时有全市场坐标参照。

---

## 3. 阶段三：接入 `fundsale/etf` 与 `fund/detail`（标的自动识别、映射校验与日度资金流）

### 3.1 已核实外部数据源与字段契约

1. **`POST https://ai2.jiucaishuo.com/api/fundsale/etf`**（来自 `https://funddb.cn/tools/etf`）
   - 请求体：`{"etf_id": 2, "type": "pc", "page": 1, "page_size": 200}`（注：`etf_id=2` 为“规模流入”视图，返回字段最全；实测全市场 `total = 2120` 只）。
   - 关键字段：
     - 身份与分类：`fund_int_code`（6位场内代码）、`fund_name`、`_fullname`、`category_0` / `category_1` / `category_2`、`setup_date`（成立日期）、`lianjie_code`（场外联接代码）
     - 指数映射：`gaikuang_genzongcode`（如 `"000015.SH"`、`"000905.SH"`、`"Au9999.SGE"`）、`gaikuang_genzongzhishu`（如 `"红利指数"`、`"中证500"`）
     - 规模与真实资金流（T-1）：`guimo_date`、`guimo_zuixin_guimo`（亿元）、`guimo_zuixin_fene`（亿份）、`guimo_7` / `guimo_30`（规模变动亿元）、**`guimo_fene_7` / `guimo_fene_30`（7日/30日份额净申赎变动，亿份——已剥离净值涨跌）**
     - 折溢价与流动性：`cj_money`（成交额元）、`current_price`、`zxjz`（最新净值）、`gsjj`（预估净值 IOPV）、`diff_deal_price` / `jt_deal_price` / `hexin_zheyijia`（折溢价率 %）
     - 费率与申赎状态：`feilv_guanlifei`（管理费 %）、`feilv_tuoguanfei`（托管费 %）、`sg_status` / `sh_status`
2. **`GET https://ai2.jiucaishuo.com/api/fund/detail?fund_code={code}`**（来自 `https://funddb.cn/fund/detail?fund_code=510510`）
   - 返回 `index_corr` 数组，如 `[{"code": "000905.SH", "corr": 0.9783, "market": "a", "name": "中证500"}]`，用于校验 ETF 净值与指数的历史回归相关度；同时包含 `fund_jz`（最新净值）与 `fund_create_time`。
3. **`GET https://config.jiucaishuo.com/guline/{code}_pe.json`**（可选兜底）
   - 返回估值页面挂载指数，如 `{"code": -100, "data": {"code": "000905.SH"}}`。
4. **跨源净值对账接口（可选辅助工具）**
   - `GET https://ai2.jiucaishuo.com/api/fund/earn-line?fund_code={code}&date=1000` 与 `POST https://ai2.jiucaishuo.com/api/fund/achieve` 提供场外单位/累计净值序列，仅用作未来人工核对行情折算与分红一致性的对账审计工具，不替代场内 `candles`。

### 3.2 数据库表设计（Alembic 迁移）

**核心原则**：不将全市场 2120 只基金全部写入 `instruments` 研究表；全市场筛选缓存只作元数据查询索引，**只有配置内（`instruments`）ETF 才逐日沉淀日度资金流与折溢价历史**。

1. **`etf_catalog_profiles`（配置内 ETF 元数据与档案补充表）**
   - `instrument_code` (`String(6)`, PK, FK → `instruments.instrument_code`)：ETF 证券代码。
   - `fund_full_name` (`String(120)`, NULL)：基金全称/源简称。
   - `category_primary` (`String(40)`, NULL)：源一级分类（如 `股票型ETF`、`跨境(QDII)ETF`、`商品型ETF`）。
   - `category_tag` (`String(64)`, NULL)：源热门板块标签（如 `沪深300`、`红利`、`黄金`、`芯片`）。
   - `tracking_index_code` (`String(32)`, NULL)：源披露跟踪指数完整代码（如 `000905.SH`）。
   - `tracking_index_name` (`String(100)`, NULL)：源披露跟踪指数中文名。
   - `index_corr` (`Numeric(8, 6)`, NULL)：`fund/detail` 返回的净值–指数相关度 `0~1`，仅作辅助校验，不单独作为法定关联依据。
   - `setup_date` (`DATE`, NULL)：基金成立日期。
   - `management_fee_pct` (`Numeric(8, 4)`, NULL)：年管理费率（%）。
   - `custody_fee_pct` (`Numeric(8, 4)`, NULL)：年托管费率（%）。
   - `linked_otc_code` (`String(6)`, NULL)：场外联接基金代码，保留前导零；可空。
   - `source_url` (`String(255)`, NOT NULL)：来源接口标识。
   - `collected_at` (`DateTime(timezone=True)`, NOT NULL)：最近档案核验更新时间戳。

2. **`etf_flow_daily`（配置内 ETF 每日规模份额与折溢价沉淀表）**
   - `instrument_code` (`String(6)`, PK, FK → `instruments.instrument_code`)：ETF 证券代码。
   - `trade_date` (`DATE`, PK)：源规模/行情基准日期（取 `guimo_date` 或 `nav_dt` 对应的真实源日期，非采集日）。
   - `unit_shares_100m` (`Numeric(18, 4)`, NULL)：最新总份额，单位亿份（源 `guimo_zuixin_fene`）。
   - `aum_100m` (`Numeric(18, 4)`, NULL)：最新资产规模，单位亿元人民币（源 `guimo_zuixin_guimo`）。
   - `net_share_flow_7d_100m` (`Numeric(18, 4)`, NULL)：近 7 日份额净变动，单位亿份（源 `guimo_fene_7`，正为净申购、负为净赎回）。
   - `net_share_flow_30d_100m` (`Numeric(18, 4)`, NULL)：近 30 日份额净变动，单位亿份（源 `guimo_fene_30`）。
   - `discount_premium_pct` (`Numeric(10, 4)`, NULL)：二级市场收盘折溢价率百分数（负为折价、正为溢价；优先取当日收盘/昨日已定估值折溢价 `t-1_deal` 或 `diff_deal_price`，并在注释标明对应采集时点）。
   - `purchase_status` (`String(32)`, NULL)：源申购状态（如 `开放申购`、`暂停申购`）。
   - `redeem_status` (`String(32)`, NULL)：源赎回状态。
   - `collected_at` (`DateTime(timezone=True)`, NOT NULL)：入库或修订时间戳。

3. **独立任务登记（`jobs` 表）**
   - 插入 `job_id = 7`：`schedule_enabled = True`、`scheduled_time = '01:25'`（北京时间，待 `guimo_date` T-1 份额披露稳定后采集，与任务 1–6 完全互斥隔离）。

### 3.3 后端接口与核心流程设计

#### A. 全市场元数据检索与新增前预览（不静默自动建链）

* 新增模块 `api/app/etf_catalog.py`（带内存 TTL 缓存，如 30 分钟，避免频繁全量翻页请求 `fundsale/etf`；共 ~11 页 `page_size=200` 或支持后续按代码搜索）。
* **`GET /instruments/preview/{code}`**：
  - 用户输入 6 位 ETF 代码后调用：
    1. 检查本地是否已存在 `instruments`；
    2. 查询 ChatBI 近 30 日行情确认证券有效（复用现有 [main.py](../../../api/app/main.py#L144-L155) 逻辑）；
    3. 并发抓取 `fundsale/etf` 匹配条目（若存在）+ `fund/detail?fund_code={code}`；
    4. 对比本地 `research_indices` 与 `sentiment_categories` 给出**“建议映射草稿”**（不落库）：
       - 跟踪指数是否在 `research_indices` 已存在（若已存在则可直接复用现有 Task 4 指数估值；若不存在则标明为“新指数，本次不自动加入估值采集，或需人工扩展指数池”）；
       - 是否在 `national_team_instruments` 覆盖范围内；
       - 返回：`code`、`name`、`setup_date`、`category_primary`、`category_tag`、`management_fee_pct`、`custody_fee_pct`、`tracking_index_code`、`tracking_index_name`、`index_corr`、`index_in_research_pool`（bool）。
* **调整 `POST /instruments`**（向后兼容原 `{ "code": "510510" }` 请求体）：
  - 新增可选字段：`confirm_index_link: bool = False`、`tracking_index_code: str | None = None`、`mapping_evidence: str | None = None`。
  - 若 `confirm_index_link=True` 且所传指数在 `research_indices` 中存在（或用户显式确认登记新 6 位指数且提供有效完整代码，需严格校验格式与 ChatBI 指数存在性），**仅在用户显式确认后**写入 `etf_catalog_profiles` 与 `instrument_index_links`，**绝不凭相关性自动覆盖已有映射或私自启用策略**。
  - 若第三方 `fundsale/etf` 暂时不可用，**不影响原有核心注册链路**（`instruments` 与任务 1 行情/权益/免费历史回补照常执行，档案字段留空并记录提示）。

#### B. 日度截面采集与资金流沉淀（`api/app/etf_flow.py` + `etf_flow_routes.py`）

* **任务 7 执行逻辑**：
  1. 读取 `instruments` 中全部 `collection_enabled == True` 的标的列表；
  2. 分页拉取 `fundsale/etf`（`etf_id=2`）直到覆盖所有配置内代码（或全部扫描一次后按配置代码过滤入库），对缺失或未上市/退市代码在 `Run.logs` 记录 `skipped/missing`；
  3. 对命中的每只配置 ETF：更新/补全 `etf_catalog_profiles` 基本档案，并按 `(instrument_code, guimo_date)` 幂等写入 `etf_flow_daily`（`guimo_date` 为源真实份额日期；仅当关键数值发生变化时更新 `collected_at`）；
  4. 明确**暂不把 `etf_flow_daily` 直接写入可启用策略规则**：新表先在前端“投研分析”展示，并在未来本地积累超过 120 个交易日后，再作为候选外部因子进入 `research_factor_context.py`（如 `etf_share_inflow_7d` / `etf_discount_opportunity`）。
* **新增查询路由（`api/app/etf_flow_routes.py`）**：
  - `GET /etf-flows/{code}/summary`：返回单 ETF 最新档案（费率、成立日、跟踪指数与相关度、最近份额、7/30 日份额变动、最新折溢价及本地累积起止日/总天数）。
  - `GET /etf-flows/{code}/series?start=...&end=...`：返回 `etf_flow_daily` 闭区间历史，供图表展示；不足历史天数时返回真实稀疏点，不插值补零。
  - `GET /etf-flows/job` / `PUT /etf-flows/job` / `POST /etf-flows/job/run`：任务 7 调度配置、状态与立即触发接口。

### 3.4 前端设计与交互（阶段三）

1. **数据管理 → 标的配置（[Instruments.tsx](../../../web/src/pages/Instruments.tsx)）**
   - **新增 ETF 两步预览确认流**：
     - 输入 6 位代码点击 **`核验并预览`**（或保留一键确认兜底），行内/抽屉卡片展示来自预览接口的「名称、成立日期、管理/托管费率、源跟踪指数 + 净值相关度、是否已在指数估值池、是否在国家队范围」；
     - 若跟踪指数已在本地 `research_indices` 中，提供默认勾选框：`☑ 同时建立与指数 {index_code} 的估值关联（核验依据：基金披露跟踪指数且相关度 {corr}）`；若不在，提示“该指数暂未纳入 Task 4 指数估值池，当前仅采集 ETF 行情”；
     - 点击 **`确认新增并启动采集`** 提交 `POST /instruments`，沿用现有通知条跳转任务日志与因子页面。
   - **标的配置表格增量信息**：在「代码 / 名称」列下以低饱和徽章（`badge-neutral`）展示所属标签、费率与「关联指数：`000905.SH`」（未关联显示“未映射指数”），方便一眼看清映射完整度。

2. **数据管理 → 任务与运行记录（[Jobs.tsx](../../../web/src/pages/Jobs.tsx)）**
   - 任务标签页增加第 7 项：`["etf-flows", "ETF档案与份额流"]`（请求 `/etf-flows/job`）。
   - 收起口径说明明确：“拉取配置内 ETF 的管理费率、成立日、跟踪指数关联参考及 T-1 份额净变动/折溢价；受外部截面接口限制，仅从首次采集日起逐日沉淀，不回填历史。”

3. **我的 ETF → 研究对象（[ResearchObject.tsx](../../../web/src/pages/ResearchObject.tsx)）**
   - **头部或行情概览补充**：在 `object` 标题旁或折叠档案卡中展示等宽档案徽章（如 `费率 0.50%+0.10%`、`成立 2013-04-11`、`跟踪 000905.SH (相关度 97.83%)`）。
   - **资金维度标签页升级（原 `funds: "国家队"` → `funds: "资金与份额"`，保持 URL 参数 `tab=funds` 兼容）**：
     - 页内提供子视图切换：**`份额流与折溢价`** | **`国家队估算比例`**；
     - 对于原本**不在国家队 18 只列表内**的标的（如黄金 `518880`、创业/科创/行业主题 ETF），以前切到 `funds` 只能看到空提示；升级后默认落到 **`份额流与折溢价`** 子视图（双子图或柱线图：上为日 K 收盘价 + 7日份额净变动红绿/中性净流向柱，下为收盘折溢价率曲线），彻底补全所有配置内 ETF 的资金面分析。
     - 对早期累积天数少于 5 天的数据明确提示：`“已收集 N 个截面日（YYYY-MM-DD 起），历史日度资金流随每日任务 7 持续累积，不回填未采集历史。”`

---

## 4. 三阶段数据库迁移与文件变更清单总览

> 建议由实现代理分 3 个独立 PR / 提交按阶段依次实施与验证，每阶段自成闭环。

| 阶段 | Alembic 迁移 | 主要新增/修改后端文件 | 主要新增/修改前端文件 |
| :--- | :--- | :--- | :--- |
| **阶段一** | `0020_valuation_and_technical_factors.py`（向 `research_factors` 插入 11 项新因子） | · `api/app/indicators.py`<br>· `api/app/research_factor_context.py`<br>· `api/app/research_factors.py`<br>· `api/app/main.py`（`/candles/{code}/factors` 接入全 5 类估值与 `000300.SH`）<br>· `api/app/factor_strategy_snapshot.py` | · `web/src/components/EtfFactorChart.tsx`（修复 `DEFAULT_FACTORS` 残留 `oversold_recovery`，改为按 `category` 分组弹窗与无映射提示） |
| **阶段二** | `0021_market_fear_greed_and_regime.py`（建 `market_fear_greed_daily`、`market_regime_factor_daily`；登记 `job_id=6`；插入 6 项全市场环境因子） | · `api/app/models.py`、`api/app/jobs.py`<br>· `api/app/market_sentiment.py`（新）<br>· `api/app/market_sentiment_routes.py`（新）<br>· `api/app/research_factor_context.py`<br>· `api/app/research_factors.py`<br>· `api/app/main.py` | · `web/src/pages/Jobs.tsx`（新增任务 6 标签）<br>· `web/src/pages/ResearchObject.tsx`（情绪 Tab 支持行业/全市场双模式与五维子因子）<br>· `web/src/pages/Compare.tsx`（情绪对比增加全市场温度背景条）<br>· `web/src/pages/Sentiment.tsx`（抽离/复用全市场图表组件） |
| **阶段三** | `0022_etf_catalog_and_flows.py`（建 `etf_catalog_profiles`、`etf_flow_daily`；登记 `job_id=7`） | · `api/app/models.py`、`api/app/jobs.py`<br>· `api/app/etf_catalog.py`（新）<br>· `api/app/etf_flow.py`（新）<br>· `api/app/etf_flow_routes.py`（新）<br>· `api/app/main.py`（`GET /instruments/preview/{code}` 与增强 `POST /instruments`）<br>· `api/app/research_routes.py` | · `web/src/pages/Instruments.tsx`（两步预览核验、可选指数映射确认、档案标签）<br>· `web/src/pages/Jobs.tsx`（新增任务 7 标签）<br>· `web/src/pages/ResearchObject.tsx`（档案徽章、`funds` Tab 拓展份额流与折溢价子视图） |

---

## 5. 各阶段验收标准（Definition of Done）

每个阶段完成实现后，均须执行项目既有验证命令并满足下列验收条件：

1. **通用工程与数据库检查**
   - 后端：`cd api && ruff check app tests migrations` 通过，`pytest -q` 全通过（若配置 `etf_sentinel_test` 须执行数据库迁移往返 `upgrade head` → `downgrade -1` → `upgrade head` 与 `alembic check`，验证全部新表、新列与中文 `COMMENT` 一致）。
   - 前端：`cd web && npm run typecheck && npm run build` 零错误，Playwright 回归 `npm run test:e2e` 通过。
   - 文档：按 [AGENTS.md](../../../AGENTS.md) 同步更新 [feature-map.md](../../feature-map.md) 状态为“已实现”、[database.md](../../database.md) 数据字典及 [README.md](../../../README.md) 当前状态摘要，并执行 `git diff --check`。

2. **阶段一专项验收**
   - `GET /factors` 返回新增 11 项因子，前端 `因子标记` 弹窗按分类展示且不保留 `oversold_recovery` 死 ID。
   - 构造单元测试验证：`erp_high_percentile` / `dividend_yield_high` 严格遵守 `< etf_trade_date` 因果对齐且 `not_applicable` 不入分位；`wilder_adx14`、`above_ma250`、`relative_strength_20d_positive` 无未来数据访问；无 `000300.SH` 或无指数映射时安全降级为 `False` 且暴露清晰覆盖状态。

3. **阶段二专项验收**
   - 真实或 Mock 抓包单元测试验证：`market_fear_greed_daily` 保留 `0` 分有效、拒绝 `< 0` 或 `> 100`、重复运行幂等；再次运行仅返回近 242 日子因子时，**不会覆盖或删除本地更早日期已落库的历史子因子行**。
   - 独立任务 `job_id = 6` 与任务 1–5 的 `pg_try_advisory_lock` 互斥隔离，重入返回 409。
   - 浏览器端验证：无行业恐贪映射的 ETF 在「我的 ETF → 市场情绪」中可无阻查看「全市场温度与波指」图表；切换子因子与日期缩放无报错；亮/暗主题下均不出现红绿颜色混用。

4. **阶段三专项验收**
   - `GET /instruments/preview/{code}` 在外部 `fundsale/etf` 或 `fund/detail` 超时/失败时优雅降级（仍返回 ChatBI 行情校验结果与降级提示），不阻塞用户新增 ETF。
   - `POST /instruments` 默认不自动写未确认映射；仅显式确认关联时创建 `instrument_index_links` 并保留核验依据（含披露跟踪指数与相关度）。
   - 任务 7 仅沉淀配置内启用标的至 `etf_flow_daily`；前端「资金与份额」支持未覆盖国家队的 ETF 展示份额流/折溢价并正确渲染“积累天数较少 / 无数据”的真实状态提示。
