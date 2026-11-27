# 分类因子策略研究 v1.4.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐可观察的原子化价量、兑现、政权和外部数据因子，并在具备因果冻结输入后对每类别独立执行 50 轮策略研究。

**Architecture:** `research_factors.py` 是因子算法唯一来源，输出每日真值和图表进入日；新的外部因子上下文模块把指数估值和映射后的恐贪数据按严格早于 ETF 当日的时点对齐。冻结快照保存外部原始观测、映射和可得性说明；表达式引擎只从该类别开发段实际可用的因子中生成候选。数据库登记因子身份和 ETF–情绪类别关系，不保存因子算法。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy、Alembic、pytest、本地 PostgreSQL、JSON 快照。

**Spec:** `docs/superpowers/specs/2026-11-27-factor-strategy-research-v1-4-factor-expansion-design.md`

## Global Constraints

- 不改动生产策略、策略分配、盘前信号或 `algorithm_templates.py`。
- 只允许本地数据库读取生成冻结；本轮不访问生产环境。
- 每项新因子都必须能在因子目录和日 K 因子接口中观察，并在冻结快照中复核。
- `oversold_recovery` 不保留为可执行因子；迁移删除旧因子关系和旧目录身份。
- 未经显式 ETF–情绪映射的数据不得参与恐贪因子。
- 旧 `.local/factor-strategy-2026-11-27/` 结果只作历史记录，不覆盖。

---

### Task 1: 原子价量、兑现与市况因子

**Files:**
- Modify: `api/tests/test_research_factors.py`
- Modify: `api/app/research_factors.py`

**Interfaces:**
- Consumes: `factor_truth_rows(rows, turning, dividends, external_truth)`。
- Produces: 原子反转、兑现退出、波动率政权和趋势回踩因子的真值及首日事件标记。

- [ ] **Step 1: 写入失败测试**

新增价格序列测试：`oversold_recovery` 不再存在；收复昨高、量能带、MA20 下方、55% 收盘和下影承接独立真值；ATR 超买、RSI 超买首次转跌、下破 MA10、均线死叉、放量受阻和长上影分别触发；波动率收敛/扩张、高波动、MA20–MA60 强度和趋势回踩均不读取未来行情。

- [ ] **Step 2: 运行失败测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_research_factors.py -q`

Expected: FAIL，原因是现有目录仍保留组合因子且没有新增身份。

- [ ] **Step 3: 最小实现因子真值**

以 Wilder ATR14、Wilder RSI14、MA5/10/20/60、20/60 日波动率和 252 日 ATR 比率历史为输入，按设计规范写出固定阈值和单日/持续状态语义。`calculate_factor_events()` 保持“event 当日、state 进入首日”图表语义。

- [ ] **Step 4: 运行因子测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_research_factors.py -q`

Expected: PASS。

### Task 2: 外部估值和恐贪因果上下文

**Files:**
- Create: `api/app/research_factor_context.py`
- Modify: `api/tests/test_research_factor_context.py`
- Modify: `api/app/factor_strategy_snapshot.py`
- Modify: `api/app/main.py`

**Interfaces:**
- Consumes: ETF 行情日期、关联指数估值观测、ETF–恐贪类别映射后的情绪观测。
- Produces: 每个 ETF 日期对应的 `valuation_low_percentile`、`valuation_high_percentile`、`sentiment_extreme_fear`、`sentiment_fear_rebound`、`sentiment_extreme_greed` 真值和可审计上下文。

- [ ] **Step 1: 写入失败测试**

测试同日估值和情绪不会在 ETF 当日使用；只允许此前最近观测；PE/PB 无效值不参与分位；恐惧回升仅在首次上升时标记；未映射数据返回不可用全假真值与覆盖说明。

- [ ] **Step 2: 运行失败测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_research_factor_context.py -q`

Expected: FAIL，原因是上下文模块不存在。

- [ ] **Step 3: 最小实现上下文和接口接入**

基于 `rolling_percentiles()` 计算本地历史分位，按严格早于 ETF 交易日的 as-of 对齐；把外部真值传给 `factor_truth_rows()`。日 K 因子接口在本地数据库读出关联指数和情绪映射并复用同一上下文函数。

- [ ] **Step 4: 运行上下文测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_research_factor_context.py api/tests/test_research_factors.py -q`

Expected: PASS。

### Task 3: 因子身份、情绪映射和冻结审计迁移

**Files:**
- Create: `api/migrations/versions/0019_factor_expansion_context.py`
- Modify: `api/app/models.py`
- Modify: `api/tests/test_strategy_factor_models.py`
- Modify: `scripts/freeze_factor_strategy_research.py`
- Modify: `api/tests/test_factor_strategy_snapshot.py`

**Interfaces:**
- Consumes: `ResearchFactor`、`InstrumentIndexLink`、`SentimentCategory`、`SentimentDaily`。
- Produces: 扩展因子目录记录、`instrument_sentiment_links` 映射表、带外部上下文和逐日停牌审计的研究快照。

- [ ] **Step 1: 写入失败测试**

测试数据库模型含具中文注释的 ETF–恐贪映射表；旧 `oversold_recovery` 不在因子目录；冻结项目保存外部上下文；没有逐日审计证据的缺日被拒绝。

- [ ] **Step 2: 运行失败测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_strategy_factor_models.py api/tests/test_factor_strategy_snapshot.py -q`

Expected: FAIL，原因是模型、迁移目录和冻结输入尚未扩展。

- [ ] **Step 3: 实现迁移和冻结输入**

迁移删除 `oversold_recovery` 的旧关系和目录条目，插入扩展因子身份，创建并只写入具备核验依据的黄金 ETF–黄金恐贪映射。冻结脚本增加明确的截止日，读取关联指数和映射后的外部观测，写入 `factor_context` 与可得性字段。跨源报告只接受按日记录的 `verified_suspensions`。

- [ ] **Step 4: 运行迁移相关测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_strategy_factor_models.py api/tests/test_factor_strategy_snapshot.py -q`

Expected: PASS。

### Task 4: 表达式门禁、类别候选池和压力成本

**Files:**
- Modify: `api/tests/test_factor_strategy_research.py`
- Modify: `api/app/factor_strategy_research.py`

**Interfaces:**
- Consumes: 扩展后的 `FACTORS`、冻结中的每日因子真值、普通与压力成本评价。
- Produces: 状态专用 `consecutive`、局部 `NOT`、不含死因子的类别候选池、开发/留出压力成本门禁与可审计淘汰原因。

- [ ] **Step 1: 写入失败测试**

测试 `NOT` 只允许作为 `all.items` 直接子项，`consecutive` 只允许直接包住持续状态因子，时间算子不能直接嵌套；晚上市 ETF 不参加对称留出；压力成本不达标会淘汰；基准超额不影响评分或淘汰；未出现的外部因子不进入该类别候选池。

- [ ] **Step 2: 运行失败测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_factor_strategy_research.py -q`

Expected: FAIL，原因是当前搜索与压力成本门禁尚未完全符合 v1.4。

- [ ] **Step 3: 实现最小研究边界**

保留开发段单独评分和连续留出账户；评分仅开发普通成本，删除基准超额；开发普通、开发压力、留出普通和留出压力的淘汰原因汇总到最终类别结论。

- [ ] **Step 4: 运行研究单元测试**

Run: `api/.venv/bin/python -m pytest api/tests/test_factor_strategy_research.py -q`

Expected: PASS。

### Task 5: 本地迁移、冻结、50 轮与报告

**Files:**
- Create: `.local/factor-strategy-2026-11-27-v1-4/input.json`
- Create: `.local/factor-strategy-2026-11-27-v1-4/manifest.json`
- Create: `.local/factor-strategy-2026-11-27-v1-4/results-50.json`
- Modify: `docs/factor-strategy-research-2026-11-27.md`
- Modify: `README.md`
- Modify: `docs/feature-map.md`

**Interfaces:**
- Consumes: 最新数据库迁移、冻结脚本和研究脚本。
- Produces: 不覆盖旧结果的 2019–2026 新快照、每类别 50 轮结论和面向人工决策的报告。

- [ ] **Step 1: 升级本地数据库和只读审计报告**

Run: `cd api && .venv/bin/alembic upgrade head`

Run: `api/.venv/bin/python scripts/backfill_free_history.py --end-date 2026-11-26 --report .local/free-history-verification-v1-4.json`

Expected: 迁移完成；审计报告逐日记录允许的真实停牌，失败或证据不足不能冻结。

- [ ] **Step 2: 生成冻结输入**

Run: `api/.venv/bin/python scripts/freeze_factor_strategy_research.py .local/factor-strategy-2026-11-27-v1-4 --start-date 2019-01-01 --end-date 2026-11-26 --verification-report .local/free-history-verification-v1-4.json`

Expected: 新目录保存 2019–2026 行情、权益、因子真值、外部上下文、停牌审计和来源摘要；不写生产策略。

- [ ] **Step 3: 执行 50 轮**

Run: `api/.venv/bin/python scripts/research_factor_strategies.py .local/factor-strategy-2026-11-27-v1-4 --rounds 50`

Expected: 每类别独立候选、开发/留出普通与压力成本结论、基准参照和淘汰原因写入新结果文件。

- [ ] **Step 4: 更新报告并全面验证**

Run: `cd api && .venv/bin/python -m pytest -q && .venv/bin/ruff check app tests migrations && cd ../web && npm run typecheck && npm run build && cd .. && docker compose --env-file .env.example config --quiet && git diff --check`

Expected: 后端测试、静态检查、前端类型和构建、编排检查与差异检查均通过；报告不把未达标策略说成可发布。
