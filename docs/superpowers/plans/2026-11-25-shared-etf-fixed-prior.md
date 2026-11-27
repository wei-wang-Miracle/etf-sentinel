# Shared ETF Fixed-Prior Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在冻结短历史中运行两套固定先验共享择时规则，输出可审计的四维验收结果而不接入生产策略。

**Architecture:** 保留 `shared_etf_walk_forward.py` 的 v2.1 滚动寻优作为历史研究实现，新建固定先验研究模块和报告入口。新模块复用行情预处理、统一成交引擎、分红归属和既有代表选择逻辑，但把预热期设为 65 根且不做任何参数选择。顶底状态机修复独立完成，保持既有事件返回类型。

**Tech Stack:** Python 3.12+、pytest、ruff、冻结 JSON、现有日频回测引擎。

**Spec:** `docs/superpowers/specs/2026-11-25-shared-etf-fixed-prior-design.md`

## Global Constraints

- 所有新增说明、注释和用户可见文本使用中文。
- 不改数据库、生产环境、算法绑定、盘前信号或已注册模板。
- 固定先验与扰动矩阵不得根据结果调参或自动发布。
- 不覆盖已有研究 JSON；只允许创建新输出路径。
- 缺失的跨资产数据必须如实报告为未验证。

---

### Task 1: 固定先验信号与逐笔归因

**Files:**
- Modify: `api/app/shared_etf_research.py`
- Create: `api/tests/test_shared_etf_fixed_prior.py`

**Interfaces:**
- Produces: `FIXED_PRIOR_RULES`、`prepare_fixed_prior(rows, dividends, market, rule, decision_start, ...)`。
- Produces: 信号证据包含冻结入场规则、MA20 后跟踪状态和可追溯退出原因。

- [x] 写入突破量比上限、反转收盘位置、5% 初始风险和 MA20 后跟踪的失败测试。
- [x] 运行定向测试，确认新增函数尚不存在或行为不符合预期。
- [x] 实现两个固定先验信号路径，不修改 `prepare_shared()` 的 v2.1 语义。
- [x] 重跑定向测试和原共享研究测试。

### Task 2: 全期验收与扰动报告

**Files:**
- Create: `api/app/shared_etf_fixed_prior.py`
- Create: `api/tests/test_shared_etf_fixed_prior.py`
- Modify: `scripts/research_shared_etf.py`

**Interfaces:**
- Consumes: `prepare_fixed_prior`、冻结 universe、统一 `simulate()`。
- Produces: `run_fixed_prior(universe, cutoff)`，返回代表、连续账本、分市况记分卡、压力测试、扰动矩阵、合成视图、现金参考和跨资产缺失状态。

- [x] 为 65 根预热、季度市况、参数高原、合成曲线和现金参考写失败测试。
- [x] 运行定向测试确认失败。
- [x] 实现单次连续评估、代表锁定、普通/压力成本、季度分段和验收布尔项。
- [x] 实现单轴扰动和跨资产输入覆盖检查；禁止候选排序或参数选择。
- [x] 让脚本默认运行固定先验路径并保持不覆盖输出的契约。
- [x] 重跑定向测试。

### Task 3: 顶底状态机单调保护修复

**Files:**
- Modify: `api/app/algorithm_templates.py`
- Modify: `api/tests/test_algorithm_templates.py`
- Modify: `docs/turning-points.md`
- Modify: `docs/superpowers/specs/2026-11-25-unified-turning-factor-design.md`

**Interfaces:**
- Preserves: `turning_events(rows, dividends, parameters=None)` 返回 `dict[str, str]`。
- Produces: 每个持有段内单调不降的 ATR 回撤保护，并在背景连续天数超过阈值时持续保持重武装。

- [x] 用 ATR 激增和连续背景超过阈值的序列写失败测试。
- [x] 运行定向测试确认失败。
- [x] 最小化修改状态机并保持默认输出和现有模板快照不变。
- [x] 重跑顶底及共享研究测试。

### Task 4: 冻结实证、文档与全量核验

**Files:**
- Modify: `README.md`
- Modify: `docs/feature-map.md`
- Modify: `docs/single-etf-strategies.md`
- Modify: `docs/shared-etf-walk-forward.md`

- [x] 修正共享验证表格分隔列数并更新固定先验的离线状态、冻结实证和缺失迁移数据。
- [x] 在新输出路径运行完整冻结研究，核验输入和代码摘要。
- [x] 运行 Ruff、全量 pytest、`docker compose --env-file .env.example config --quiet`、文档链接与 `git diff --check`。
- [x] 对照报告中的代表数、完整交易数、扰动点数、跨资产缺失状态和验收结论，记录未验证的数据库与生产链路。
