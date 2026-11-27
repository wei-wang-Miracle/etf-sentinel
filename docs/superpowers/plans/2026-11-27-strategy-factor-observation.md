# 策略与因子观察重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans` 按任务执行。步骤以复选框跟踪。

**Goal:** 将策略研究重构为代码计算指标/因子、代码组合策略、数据库保存因子身份及关系、用户观察解释并显式采用当前策略的清晰结构。

**架构：** Python 定义因子与策略身份，提供因果日序事件；SQLAlchemy/Alembic 保存因子目录、策略因子关系、比较关系及每 ETF 当前策略分配。保留统一回测账本和单次输入、结果证据，盘前信号直接引用当前策略分配。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、React、TypeScript、Vite、ECharts、pytest。

**Spec:** `docs/superpowers/specs/2026-11-27-strategy-factor-observation-design.md`

## 全局约束

- 用户可见文案与新增注释使用中文；稳定代码身份使用英文 snake_case。
- 指标和因子算法仅在代码，不把可执行算法存入数据库；不提供指标/因子/策略版本选择。
- 因子只用于观察和解释，不直接成为买卖信号；策略组合与风控由服务端代码控制。
- 数据库迁移删除旧策略绑定、保存版本、观察批次、信号和执行关联；保留行情/权益、账户真实持仓/委托、统一回测基础设施。
- 每只 ETF 最多一个当前策略分配；只有显式采用/替换/暂停影响盘前信号。
- 不覆盖工作区既有未提交修改；不建立 worktree；不添加兼容层。

---

### 任务一：因果因子计算与静态目录

**文件：**新增 `api/app/research_factors.py`、`api/tests/test_research_factors.py`；修改 `api/app/algorithm_templates.py`、`api/app/shared_etf_research.py`（仅抽取可复用逻辑所必需）。

- [ ] 先写首批因子目录集合与元数据一致性测试。
- [ ] 为 MA5 上穿 MA20、20日箱体突破、放量突破、ATR 超跌/修复定义逐日因果输出，并覆盖 RSI14/ATR14 Wilder 初值、预热、零波幅和缺值。
- [ ] 复用现有 `turning_events()` 作为顶部/底部因子来源，不改变已验证行为。
- [ ] 运行因子单元测试及现有顶底/共享研究测试。

### 任务二：数据库因子/策略关系与破坏性迁移

**文件：**修改 `api/app/models.py`；新增 `api/migrations/versions/0018_strategy_factor_architecture.py`；新增迁移/目录测试。

- [ ] 先写模型元数据与目录同步测试。
- [ ] 新建 `research_factors`、`research_strategy_factors`、`instrument_strategy_assignments`，所有字段有中文注释；策略目录由代码持有。
- [ ] 比较记录增加当前策略-因子关系表。
- [ ] 迁移删除 `strategy_execution_links`、`strategy_signals`、`strategy_observations`、`strategy_research_batches`、`saved_strategy_versions`、`saved_strategies` 及旧 `strategy_comparisons` 后重建干净比较表；明确旧研究/信号数据不保留。
- [ ] 保留 `account_entrusts`、`account_holdings_snapshots`、`backtest_runs`、行情、权益和任务记录。
- [ ] 在全新和有旧数据的独立库校验 `alembic upgrade head`、目录和清理范围；验证不可逆迁移拒绝降级；完成本机业务库升级。

### 任务三：当前策略比较与采用 API

**文件：**重构 `api/app/strategy_workbench.py`、`api/app/algorithm_templates.py` 的注册目录；新增/更新相应 API 测试。

- [ ] 比较请求接收 `strategies`（策略身份列表）而非策略版本；服务端按当前代码执行，不接受用户传规则。
- [ ] 比较保存当次规则摘要、行情/权益输入、触发因子输出、结果和实际因子关系。
- [ ] 替换“保存版本”端点为显式“采用本次比较中的策略”操作；每 ETF 单条分配，替换须显式确认，可暂停。
- [ ] 删除未被调用的版本列表/保存版本/旧观察批次/旧复盘代码及相关模型引用，不留兼容路由。
- [ ] 测试比较成功/失败、快照验证、明确采用、重复采用、替换冲突、暂停和单 ETF 唯一分配。

### 任务四：当前分配驱动的盘前信号

**文件：**重构 `api/app/strategy_plans.py`、`api/app/strategy_lab.py`、`api/app/jobs.py` 中任务5的调用；新增 API/服务测试。

- [ ] 计划计算读取当前分配并解析当前代码策略，不读历史规则版本。
- [ ] 信号表以 `assignment_id + execution_date` 幂等，保留决策时行情、因子输出、理由、数据截止及账户证据快照。
- [ ] 保留交易时点、分红/行情核验、仓位未知不补零、人工成交关联约束。
- [ ] 启停/替换后既有信号证据不可变；旧信号和旧执行关联由迁移删除。
- [ ] 测试无分配不产信号、显式启用才产信号、重复生成幂等、过开盘时间拒绝、真实委托核对及跳过边界。

### 任务五：因子目录、策略解释与行情图标记

**文件：**在 `api/app/main.py` 注册只读因子接口；新增 `web/src/components/EtfFactorChart.tsx`，修改 `web/src/components/KLine.tsx`、策略页面及测试，删除旧版算法说明、顶底图层和版本详情组件。

- [ ] API 返回数据库目录及代码计算因子事件，使用核验截止、预热和因果行情。
- [ ] 日 K 区分事件类别、日期、因子说明；只增加展示开关，不改变策略计算。
- [ ] 策略库展示因子组成和解释，比较/采用当前策略；移除策略版本列表与版本对比表达。
- [ ] 完成 API 测试及 Playwright 图表/策略工作流测试。

### 任务六：文档、回归和交付审计

**文件：**修改 `README.md`、`docs/feature-map.md`、`docs/single-etf-strategies.md`、`docs/backtesting.md`、`docs/database.md`、`AGENTS.md`（仅必要时）。

- [ ] 文档清楚说明指标/因子/策略边界、因子观察、策略采用、研究不自动启用和本地破坏性迁移。
- [ ] 检查旧表/旧 API/前端字段不再有运行时引用。
- [ ] 执行后端 `ruff check app tests migrations`、`pytest -q`；报告独立数据库测试是否跳过。
- [ ] 执行前端 `npm run build`、`npm run typecheck`、必要 Playwright 用例。
- [ ] 执行 Compose 配置检查、`git diff --check`、文档本地链接检查，并审阅所有差异与初始工作区状态。
