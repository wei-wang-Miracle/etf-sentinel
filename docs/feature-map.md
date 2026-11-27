# 功能地图

本文是 ETF Sentinel 功能归属和状态的统一入口，由开发代理随每次功能变更维护。
平台定位与使用方式见 [README](../README.md)，协作规则见 [AGENTS](../AGENTS.md)。
当前已实现标的配置、历史日行情、日 K、行业恐贪、国家队持仓及配置内 ETF 真实持仓与委托同步。投研支持只读因子观察、同 ETF 策略比较、单 ETF 复盘及显式采用；当前启用的策略分配可生成盘前计划并人工核对累计委托，不提供自动交易。

## 业务域边界

以下是用于归类后续需求的初始结构，可以根据实际需求调整。
它不代表功能清单、页面导航、代码目录或开发排期。

| 业务域 | 负责的问题 | 边界 |
| --- | --- | --- |
| 数据基础 | 研究对象、数据来源、数据获取与质量 | 提供可追溯的数据，不负责投资决策 |
| 投研分析 | 对可交易ETF及其关联因子进行观察、比较与分析 | 提供研究依据，不直接等同于交易信号 |
| 策略研究 | 定义择时规则、参数及验证方法 | 负责规则、参数与历史模拟实验；实时信号由信号域承接 |
| 信号与提示 | 根据策略和截至当时的数据产生、解释及提示买卖信号 | 提示不等于实际成交，不默认包含自动下单 |
| 投资记录与复盘 | 记录实际操作并对照研究与信号复盘 | 已同步配置内持仓/成交；实际核算、研究模拟及信号执行分别解释 |
| 工程基础 | 应用运行、配置、部署和通用界面规范 | 支撑业务，不承载择时规则 |

跨域功能指定一个主归属，并列出依赖域。优先复用已有概念和能力，只有现有
边界无法合理容纳需求时才调整结构，并记录调整原因。

## 功能登记

每个明确提出的功能登记一行，随实现更新。状态使用“待澄清”“已确认待实现”
“实现中”“已实现”“已移除”；探索想法留在 README 的待讨论事项中。
“已实现”须有实际代码与相关验证依据，尚未验证的链路明确注明。

| 功能 | 主归属 | 状态 | 依赖与边界 | 设计或实现入口 |
| --- | --- | --- | --- | --- |
| 研究图表维度与信息层级 | 投研分析 | 已实现 | 四维度横向标签、键盘切换、URL 恢复与按需加载；常规口径收于图后折叠说明，实际错误和缺失保留可见；国家队源不支持的 ETF 解释覆盖限制，不引导无效采集 | [研究对象](../web/src/pages/ResearchObject.tsx)、[使用说明](research-workbench.md#研究对象)、[浏览器回归](../web/tests/research.spec.ts) |
| 指标计算 | 策略研究 | 已实现（内部） | MA、RSI、ATR、量比等在代码中计算，不建库、不配置、不单独展示版本 | [指标公式](../api/app/indicators.py)、[口径](single-etf-strategies.md) |
| 模拟买卖点与每日仓位副图 | 策略研究 | 已实现 | 复用所选策略冻结账本，0%至100%收盘仓位中性色柱，与日 K、买卖点、缩放联动；半资金按完整账户计算，缺失不补零，真实标记不改变模拟仓位；其他行情保留成交量 | [仓位设计](superpowers/specs/2026-11-09-strategy-position-chart-design.md)、[比较图](../web/src/components/StrategyComparison.tsx)、[图表验证](../web/tests/position-chart.spec.ts) |
| 指标来源分类与日 K 微观条件 | 策略研究 | 已移除 | 旧自定义策略的条件配置与逐条件诊断已不属于当前用户流程，相关保存记录由迁移0014清理；固定模板内部因子不开放编辑 | [共享算法策略](single-etf-strategies.md) |
| 创建策略因子拖拽配置 | 策略研究 | 已移除 | 因子只供观察，策略由代码组合；用户不编辑或组合因子 | [策略与因子](single-etf-strategies.md) |
| 面向个人的单 ETF 策略流程 | 策略研究 | 已实现 | 支持非持仓 ETF，查看策略与因子关系、比较、确认采用、替换或暂停；每只 ETF 至多一条当前分配 | [当前说明](single-etf-strategies.md)、[我的策略页](../web/src/pages/MyStrategies.tsx) |
| 同 ETF 策略比较 | 策略研究 | 已实现 | 对比箱体突破、底部确认、复合反转与持有参照；历史保留该次关系和输入结果快照，不作为可选算法版本 | [比较页](../web/src/components/StrategyComparison.tsx)、[接口](../api/app/strategy_workbench.py)、[回归](../web/tests/strategy-template.spec.ts) |
| 前后端工程初始化 | 工程基础 | 已实现 | 已扩展业务页面、迁移及采集；Docker Hub 连接受阻，三容器启动未验证 | [前端](../web/src/App.tsx)、[API](../api/app/main.py)、[Compose](../compose.yaml)、[初始化清单](superpowers/plans/2026-11-05-initialize.md) |
| 投研简报视觉融合 | 工程基础 | 已实现 | 暖纸亮色、宋体标题、朱红操作强调、连续指标条；保留暗色和业务语义色 | [设计契约](design-contract.md)、[主题变量](../web/src/styles/tokens.css) |
| ETF 研究案卷重设计 | 工程基础 | 已实现 | 协作投研、策略、信号、复盘及数据域；对象与日期连续、单对象标题、三阶段策略、只读快照、适用与历史信号、双主题及键盘读数；不改变投资或任务规则 | [总设计](../DESIGN.md)、[实施验收](design/frontend-validation.md) |
| 前端视觉精修 | 工程基础 | 已实现 | 统一导航线条图标、筛选控件、间距和图注字号；中性选中态、窄屏换行；不改变业务口径 | [设计契约](design-contract.md#前端视觉精修)、[共享样式](../web/src/styles/global.css) |
| 数据库语义与注释规范 | 工程基础 | 已实现 | 原地重命名迁移，不删除行情 | [数据库说明](database.md) |
| 本地一键启动 | 工程基础 | 已实现 | Docker仅运行PostgreSQL；本机前后端支持start/restart、进程互斥与安全清理 | [启动脚本](../scripts/start-local.sh) |
| ETF 统一标的配置 | 数据基础 | 已实现 | 预置 23 只；输入六位代码，ETF 行情源确认后登记并尝试启动任务1；可查采集记录和入库区间，直达日 K 观察因子。不自动建立估值或国家队映射、不创建或启用策略 | [配置页](../web/src/pages/Instruments.tsx)、[标的接口](../api/app/main.py)、[功能说明](daily-data.md) |
| 定时历史日行情与权益批量核验 | 数据基础 | 已实现 | 行情仅采集启用标的；任务1随后核验全部配置ETF权益，逐只提交并分别记录；权益失败不回滚行情；PostgreSQL、ChatBI、分区间恢复与互斥 | [采集](../api/app/collection.py)、[调度](../api/app/jobs.py)、[说明](daily-data.md)、[迁移](../api/migrations/versions/0001_daily_data.py) |
| 日 K 与成交量展示 | 投研分析 | 已实现 | 依赖本地行情；以前复权 OHLC 连续展示已核验份额折算，MA5/10/20/30/60基于展示序列，成交量保留源数值；不提供实时行情 | [行情页](../web/src/pages/Market.tsx)、[图表](../web/src/components/KLine.tsx) |
| 行情因子观察 | 投研分析 | 已实现 | 11 项可观察事件或状态，默认阶段顶底与超跌后止跌修复、允许同日叠加，显示权益覆盖和缺失状态；开关只影响图层 | [因子目录](../api/app/research_factors.py)、[行情接口](../api/app/main.py)、[图层](../web/src/components/EtfFactorChart.tsx)、[顶底说明](turning-points.md) |
| ETF顶底参数模板与历史检验 | 策略研究 | 已实现 | 20只宽基ETF按跟踪指数映射六类固定参数模板，属于统一顶底因子的敏感度差异，不提供第二套前端算法或来源切换；50轮历史研究总体58.1%（61/105），近期观察不足以证明80% | [指标说明](turning-points.md)、[50轮分类检验](turning-points-validation.md)、[算法模板](../api/app/algorithm_templates.py) |
| 当前策略分配与盘前计划 | 策略研究 | 已实现 | 显式采用后生成后续计划，按策略分配和执行日保留首份，历史计划及人工交易核对保留证据；迁移0018清理旧策略域 | [信号](../api/app/strategy_lab.py)、[迁移0018](../api/migrations/versions/0018_strategy_factor_architecture.py) |
| 宽基 ETF 箱体突破优化验证 | 策略研究 | 已实现 | 30 轮离线候选，共用回测引擎；20 只 ETF 的留出验证暂无标的达到 80% 胜率门槛 | [验证报告](range-breakout-validation.md)、[复现脚本](../scripts/research_range_breakout.py) |
| 逐ETF多因子历史研究 | 策略研究 | 仅历史研究 | 50轮拟合总体88.8%（166/187），已观察区间64.3%（27/42）。不进入当前策略目录 | [历史报告](multifactor-research-validation.md)、[研究计算](../api/app/multifactor_research.py) |
| 宽基 ETF 共享择时固定先验验收 | 策略研究 | 已实现（离线，未发布） | 复用行情、权益、统一回测与固定代表；65 根预热后全期连续评估共享突破和左侧反转，输出分市况、防守、参数高原、现金参考及三只迁移标的的独立结果。研究冻结可只读本地库，并在输入层标准化份额折算；当前覆盖仅 2024—2026 年，不参与算法绑定与盘前信号 | [验收报告](shared-etf-walk-forward.md)、[外部验证设计](superpowers/specs/2026-11-27-shared-etf-external-validation-design.md)、[固定先验设计](superpowers/specs/2026-11-25-shared-etf-fixed-prior-design.md)、[冻结入口](../scripts/freeze_shared_etf.py)、[离线入口](../scripts/research_shared_etf.py) |
| 分类因子策略研究 | 策略研究 | 已实现（离线，未发布） | 冻结全量已核验 ETF、权益、指数映射和逐日因子真值；每个类别独立完成 50 轮、每轮 3 个可读因子表达式候选，统一 ATR 风控、连续持仓留出、跨边界交易归因、压力成本和同成本持有比较。父代评分屏蔽低样本并封顶 PF，类别按独立跟踪单位去重，单指数或单 ETF 类别明确标为单标的证据；截至 2026-11-26 的 1,350 个校准候选均不可发布，不创建策略绑定或盘前信号 | [最终结论](factor-strategy-research-2026-11-27.md)、[原始设计](superpowers/specs/2026-11-27-category-factor-strategy-research-design.md)、[校准设计](superpowers/specs/2026-11-27-factor-strategy-research-calibration-design.md)、[冻结入口](../scripts/freeze_factor_strategy_research.py)、[研究入口](../scripts/research_factor_strategies.py) |
| A股图表规范与可追溯图注 | 投研分析 | 已实现 | 跨行情、国家队、回测、恐贪；红涨绿跌、均线、执行日买卖标记、图注与免责声明；行情标签页明确为前复权展示，顶底因子明确为因果复权计算 | [设计契约](design-contract.md#klinechart)、[图注](../web/src/components/ChartCaption.tsx)、[图表工具](../web/src/lib/chart.ts) |
| 行业恐贪历史采集 | 数据基础 | 已实现 | 独立数据源与任务；首次五年，后续增量 | [行业恐贪说明](industry-sentiment.md) |
| 行业恐贪概览与历史展示 | 投研分析 | 已实现 | 依赖行业恐贪入库；情绪着色、双轴合图，不直接生成信号 | [行业恐贪说明](industry-sentiment.md) |
| 国家队18只ETF估算比例采集 | 数据基础 | 已实现 | 独立任务3，固定基准全量核验、增量写入；不保存源价格 | [国家队持仓说明](national-team.md) |
| 国家队持仓与日K对照 | 投研分析 | 已实现 | 18只已纳入行情采集，复用同代码日K，缺失不补零；MA5/10/20/30/60与可追溯图注；不作为真实持仓或信号 | [国家队持仓页](../web/src/pages/NationalTeam.tsx) |
| 统一策略注册与日频回测 | 策略研究 | 已实现 | 配置内ETF动态资格的持有、均线与动量确认规则；次日开盘、整手费用分红、同成本基准；买卖标记按执行日标注并同日同向合并；历史模拟非实际交易 | [策略与回测](backtesting.md)、[注册表](../api/app/strategies.py)、[引擎](../api/app/backtest.py)、[比较图](../web/src/components/StrategyComparison.tsx) |
| 当前持仓ETF策略闭环 | 策略研究 | 已移除 | 旧五候选研究、批次与采用创建已下线（迁移0013清理旧观察链）；盘前计划与人工执行核对并入单ETF流程共用，未自动采用策略 | [单ETF说明](single-etf-strategies.md)、[信号与执行](../api/app/strategy_lab.py) |
| 回测权益与不可变实验 | 数据基础 | 已实现 | 东方财富公开权益与交易日历校验；任务1批量核验全部配置ETF，也支持按ETF手动更新；完整输入/结果快照入库供新流程引用；旧实验列表/复算入口已下线 | [回测接口](../api/app/backtest_routes.py)、[批量任务](../api/app/collection.py)、[迁移0006](../api/migrations/versions/0006_backtests.py) |
| 配置内 ETF 持仓与成交同步展示 | 投资记录与复盘 | 已实现 | 同步配置内 ETF 持仓/委托成交；1000行窗口、幂等、推导费用、非配置跳过；页面展示持仓和成交；不含收益复盘 | [同步](../api/app/account_sync.py)、[接口](../api/app/account_routes.py)、[页面](../web/src/pages/Review.tsx)、[迁移0008](../api/migrations/versions/0008_account_sync.py) |
| 配置内 ETF 单标的收益复盘 | 投资记录与复盘 | 已实现 | 复用已实现同步；完整同步、权益、数量与T+1准入及显式依据确认后真实净盈亏/XIRR；统一资金的持有、MA20/MA60和现金单列，不输出不可比择时超额 | [设计](superpowers/specs/2026-11-06-configured-etf-review-design.md) |
| 全账户复盘与现金基线 | 投资记录与复盘 | 待讨论 | 需要现金余额、配置外持仓、LOF/逆回购；当前不实施 | [设计](superpowers/specs/2026-11-06-real-account-review-design.md) |

| 8个关联指数五类估值及指数日K采集 | 数据基础 | 已实现 | 20ETF映射去重、任务4、增量写入、修订证据、失败恢复 | [指数估值说明](index-valuations.md)、[采集](../api/app/index_collection.py) |
| 指数估值与走势对照 | 投研分析 | 已实现 | 中文图表优先、来源分位与本地十日历年回看分位分开；修订历史不声称原时点已知，共享算法初版不使用估值分位 | [估值页](../web/src/pages/IndexValuations.tsx)、[设计](superpowers/specs/2026-11-06-index-valuation-design.md) |
| 研究对象详情合并 | 投研分析 | 已实现 | ETF唯一主体、旧指数URL映射关联ETF、分区懒加载、五估值、情绪背景、国家队、个人摘要、研究入口与URL迁移；策略只能通过固定模板生成，不开放条件配置 | [设计](superpowers/specs/2026-11-06-research-object-design.md)、[页面](../web/src/pages/ResearchObject.tsx) |
| 横向同维度对比 | 投研分析 | 已实现 | 当前持仓默认／全部配置切换，ETF关联估值、资金与趋势；情绪单列背景；同日排名、共享指数提示、六线图、热力图与URL | [设计](superpowers/specs/2026-11-06-cross-comparison-design.md)、[页面](../web/src/pages/Compare.tsx) |

分析页采用紧凑筛选与图表优先布局，移除底部数据明细表；配置与日志保留。

后续具体功能点提出后，代理负责补充主归属、相关依赖、范围与设计入口，
再随开发更新状态。

## 维护方式

本文描述当前系统结构，具体功能方案按需单独放入 `docs/` 并在登记中链接。

- 新功能先检查与已有功能的重叠，再确定归属、入口和最小必要依赖。
- 功能调整或移除时同步更新登记及相关设计，README 中的能力摘要保持一致。
- 归属变更时更新相关条目，并简述原因；不在此积累逐次开发流水账。
- 状态、实现与验证结论保持一致，不将页面占位或依赖声明写成业务能力。

账户数据源配置：行情与账户共用 `.env` 的 `CHATBI_TOKEN`；固定源地址和
独立访问码见 `api/app/chatbi_config.py`，资金号见 Git 忽略的
`api/config/account.json`，本地和容器共用同一份配置。

三期入口、接口、确认依据及保守拒绝边界见[投研工作台说明](research-workbench.md)。
