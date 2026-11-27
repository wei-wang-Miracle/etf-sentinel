# 指标因子与 FundDB 扩展实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:executing-plans` 逐任务执行；每项以复选框记录状态，并在实现前按 `superpowers:test-driven-development` 先写失败测试。

**目标：** 在不改动生产策略、策略分配与盘前信号的前提下，扩展可观察、可用于离线研究的指标与因子，接入全市场恐贪环境和配置内 ETF 档案/份额流。

**架构：** 阶段一仅盘活本地指数估值和行情，新增纯指标与原子因子。阶段二把 FundDB 全市场恐贪作为独立任务 6，严格按 `source_date < etf_trade_date` 构造背景真值。阶段三以任务 7 从 FundDB 只沉淀配置内 ETF 的档案与日度份额流，新增 ETF 先预览、用户显式确认后才创建指数关联。

**技术栈：** FastAPI、SQLAlchemy 2、PostgreSQL、Alembic、pytest、React、TypeScript、Vite、Playwright。

**规格：** `docs/superpowers/specs/2026-11-27-indicator-factor-and-funddb-expansion-design.md`

## 全局约束

- 外部日频数据只在 `source_date < etf_trade_date` 时进入因子真值；缺日、不适用和无映射均为不可用，不补零。
- 指标和因子公式只存在 Python 代码；数据库只登记因子身份、关联关系和原始外部观测。
- 任务 6、7 分别使用 `LOCK_ID + 5`、`LOCK_ID + 6`，与任务 1 至 5 独立互斥。
- `fundsale/etf` 和 `fund/detail` 只作档案/份额流来源；不自动建立指数映射，不把份额流接入策略。
- 新表、字段和迁移必须有中文 COMMENT；同步维护 `README.md`、`docs/feature-map.md`、`docs/database.md`。
- 沿用现有三个一级导航；前端覆盖加载、空态、错误和真实数据覆盖提示。

---

### Task 1：阶段一指标算子与技术真值

**文件：**
- 修改：`api/app/indicators.py`
- 修改：`api/app/research_factors.py`
- 测试：`api/tests/test_indicators.py`
- 测试：`api/tests/test_research_factors.py`

**接口：**
- 产出 `rolling_sma(values, index, window) -> float | None`。
- 产出 `wilder_adx14(previous_high, previous_low, previous_close, high, low, close, index, state) -> tuple[float | None, float | None, float | None, dict]`。
- 产出 `drawdown_from_peak(values, index, window) -> float | None`、`consecutive_down_count(values, index) -> int`、`excess_return(values, bench_values, index, window) -> float | None`。
- `factor_truth_rows(..., benchmark_rows=None)` 计算 MA120/MA250、ADX、回撤、连跌、强势跳空及相对沪深300真值；缺基准时相对强弱为 `False`。

- [x] 编写并验证指标窗口、28 根 ADX 预热、无未来数据、深回撤/连跌/跳空和缺基准相对强弱。
- [x] 以最小纯函数实现指标，并把 8 项技术因子加入 `FACTORS` 与真值序列。
- [x] 重跑定向测试，确认通过。

### Task 2：阶段一估值扩展与快照上下文

**文件：**
- 修改：`api/app/research_factor_context.py`
- 修改：`api/app/factor_strategy_snapshot.py`
- 修改：`api/app/main.py`
- 测试：`api/tests/test_research_factor_context.py`
- 测试：`api/tests/test_factor_strategy_snapshot.py`

**接口：**
- `build_external_factor_truth(..., benchmark_rows=())` 消费 `pe`、`pb`、`xilv`、`roe`、`premium_diff` 的 `valid` 行。
- 产出 `erp_high_percentile`、`erp_low_percentile`、`dividend_yield_high`；`coverage["valuation"]` 明确列出各指标的实际覆盖。
- `GET /candles/{code}/factors` 查询关联指数估值和 `000300.SH` 指数日K；无关联或无基准时保留正常 K 线并返回不可用原因。

- [x] 编写并验证 `xilv=0`、负 ROE/ERP、`not_applicable`、严格前一日对齐、无指数映射及无沪深300序列。
- [x] 扩展上下文、快照输入和因素 API；不将源 `pct_all` 当作历史分位。
- [x] 使冻结输入与因素 API 同时传入本地 `000300.SH` 日K；缺数据明确不可用。
- [x] 重跑相关测试，确认通过。

### Task 3：阶段一目录迁移与因子观察界面

**文件：**
- 创建：`api/migrations/versions/0020_valuation_and_technical_factors.py`
- 修改：`web/src/components/EtfFactorChart.tsx`
- 修改：`web/src/styles/research-workspace.css`
- 测试：`api/tests/test_strategy_factor_models.py`
- 测试：`web/tests/turning-chart.spec.ts`

**接口：**
- 迁移登记阶段一 11 项因子，`factor_id` 与 `FACTORS` 精确一致。
- 图层选择按固定业务分类分组；支持组内全选/清空和聚焦释义；没有指数映射时展示不可用原因及标的配置入口。

- [x] 编写并验证迁移目录包含 11 项因子、前端按分类呈现且不含 `oversold_recovery`。
- [x] 新增迁移和分类图层交互，保持默认三项因子观察语义不变。
- [x] 升级本地数据库至 `0020`，重跑定向测试。
- [ ] 提交阶段一，提交信息：`feat(factors): 扩展估值与长期技术因子`。

### Task 4：阶段二全市场恐贪数据模型、采集与任务

**文件：**
- 创建：`api/app/market_sentiment.py`
- 创建：`api/app/market_sentiment_routes.py`
- 创建：`api/migrations/versions/0021_market_fear_greed_and_regime.py`
- 修改：`api/app/models.py`
- 修改：`api/app/jobs.py`
- 修改：`api/app/main.py`
- 测试：`api/tests/test_market_sentiment.py`
- 测试：`api/tests/test_strategy_factor_models.py`
- 测试：`api/tests/test_national_team_database.py`

**接口：**
- `collect_market_sentiment(run_id, fetch=source_get)` 验证 `fear-greed` 总分及五个子因子，幂等插入或修订，绝不删除本地更早的子因子记录。
- `GET /market-sentiment/overview`、`GET /market-sentiment/series`、`GET|PUT|POST /market-sentiment/job...` 与行业恐贪的任务交互一致。
- `Job.id=6` 默认 `01:15`；生命周期恢复任务 6。

- [x] 编写并验证总分零值、越界拒绝、同日修订、近 242 日子序列不删除旧数据的测试。
- [x] 实现模型、迁移、采集器、路由及调度挂接；只记录源已返回日期。
- [x] 升级本地数据库至 `0021`，完成真实源抓取与本地 API 验证。

### Task 5：阶段二全市场因子与前端观察

**文件：**
- 修改：`api/app/research_factor_context.py`
- 修改：`api/app/research_factors.py`
- 修改：`api/app/factor_strategy_snapshot.py`
- 修改：`api/app/main.py`
- 修改：`web/src/pages/Jobs.tsx`
- 修改：`web/src/pages/ResearchObject.tsx`
- 修改：`web/src/pages/Sentiment.tsx`
- 修改：`web/src/pages/Compare.tsx`
- 测试：`api/tests/test_research_factor_context.py`
- 测试：`web/tests/research.spec.ts`

**接口：**
- `build_external_factor_truth(..., market_rows=(), market_regime_rows=())` 产生六个全市场环境状态，并报告可用日期范围。
- `factor_strategy_snapshot` 在输入摘要中保留 `market_regime.first_source_date` / `last_source_date`。
- ETF 情绪页允许 `sentiment_scope=industry|market`；行业无映射时仍可查看全市场温度与波指。

- [x] 编写并验证严格早于 ETF 当日的因果对齐；本地 iVIX 分位不读取源全历史分位。
- [x] 编写并验证无行业映射 ETF 可打开全市场图表的浏览器用例。
- [x] 实现六个因子、全市场图表和任务标签；颜色仅使用情绪/图表颜色语义。
- [x] 运行阶段二单元测试、定向 Playwright、前端类型检查与构建。
- [ ] 提交阶段二，提交信息：`feat(data): 接入全市场恐贪与政权观察`。

### Task 6：阶段三 ETF 档案、预览和份额流后端

**文件：**
- 创建：`api/app/etf_catalog.py`
- 创建：`api/app/etf_flow.py`
- 创建：`api/app/etf_flow_routes.py`
- 创建：`api/migrations/versions/0022_etf_catalog_and_flows.py`
- 修改：`api/app/models.py`
- 修改：`api/app/jobs.py`
- 修改：`api/app/main.py`
- 测试：`api/tests/test_etf_catalog.py`
- 测试：`api/tests/test_etf_flow.py`
- 测试：`api/tests/test_collection.py`
- 测试：`api/tests/test_strategy_factor_models.py`

**接口：**
- `fetch_catalog_page` 解析真实 `{code,data:{lists,total}}` 包装，也接受测试用扁平列表；`fetch_fund_detail` 从 `{data:{index_corr}}` 读取相关度。
- `GET /instruments/preview/{code}` 始终返回 ChatBI 有效性结果；FundDB 超时仅追加警告，不阻断预览。
- `POST /instruments` 接受 `confirm_index_link`、`tracking_index_code`、`mapping_evidence`；默认不写 `InstrumentIndexLink`。
- `collect_etf_flows` 仅处理 `Instrument.enabled=True` 标的，并幂等更新 `EtfCatalogProfile` 与 `EtfFlowDaily`。

- [ ] 编写真实源包装解析、详情相关度提取、外部源降级、未确认不建映射、确认映射保存证据、只持久化配置内标的和流量修订的失败测试。
- [ ] 运行后端测试，确认当前缺模块或接口而失败。
- [ ] 实现表模型、迁移、30 分钟内存缓存、预览、显式关联、任务 7 与只读查询路由。
- [ ] 升级本地数据库至 `0022`，重跑阶段三后端测试。

### Task 7：阶段三标的配置与资金份额前端

**文件：**
- 修改：`web/src/lib/api.ts`
- 修改：`web/src/pages/Instruments.tsx`
- 修改：`web/src/pages/Jobs.tsx`
- 修改：`web/src/pages/ResearchObject.tsx`
- 修改：`web/src/styles/research-workspace.css`
- 测试：`web/tests/instrument-onboarding.spec.ts`
- 测试：`web/tests/research.spec.ts`

**接口：**
- 新增 ETF 先调用 `/instruments/preview/{code}`，展示真实档案与可选关联确认；FundDB 不可用时仍保留一键新增。
- `tab=funds` 仍可访问，标题改为“资金与份额”，默认呈现本地份额流/折溢价；国家队估算作为子视图。
- 少于 5 个已采集截面日显示真实积累天数与起点，不绘制虚构历史。

- [ ] 编写预览确认、降级一键新增、显式指数勾选、资金流空态和少量样本提示的失败 Playwright 测试。
- [ ] 运行定向浏览器测试，确认新增断言失败。
- [ ] 实现双步预览与资金份额子视图，维持键盘焦点、窄屏与 URL 参数行为。
- [ ] 运行全部前端 E2E（单 worker）及类型/构建检查。

### Task 8：文档、全量验证和交付提交

**文件：**
- 修改：`README.md`
- 修改：`docs/feature-map.md`
- 修改：`docs/database.md`
- 修改：`docs/single-etf-strategies.md`

- [ ] 记录任务 6/7、因子目录、数据因果边界、FundDB 份额流不参与策略的当前状态。
- [ ] 执行 `cd api && .venv/bin/python -m pytest -q` 与 `.venv/bin/ruff check app tests migrations`。
- [ ] 执行 `cd web && npm run typecheck && npm run build && npm run test:e2e -- --workers=1`。
- [ ] 执行 `docker compose --env-file .env.example config --quiet`、`alembic check`、`git diff --check`，核对迁移与模型 COMMENT。
- [ ] 提交阶段三及文档，提交信息：`feat(data): 增加ETF档案与日度份额流`。
