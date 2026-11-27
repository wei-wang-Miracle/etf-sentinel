# 分类因子策略研究校准 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 校准分类因子策略研究的父代选择、留出统计与防守观察口径，并在原冻结输入上重新运行 50 轮离线研究。

**Architecture:** 开发段评分增加样本门槛、PF 封顶与期望归一化；表达式演化从一个全局父代池改为按类别独立的候选历史。留出期继续使用连续账户净值，但将新开仓交易与跨边界持仓分开；熊市防守只输出观察字段，不参与生产发布。

**Tech Stack:** Python 3、pytest、ruff、现有 FastAPI 研究模块、冻结 JSON 输入。

**Spec:** `docs/superpowers/specs/2026-11-27-factor-strategy-research-calibration-design.md`

## Global Constraints

- 不修改生产策略模板、策略注册、策略分配、盘前信号或数据库。
- 不修改 11 个既有因子、风险基线、成本参数或冻结输入。
- 留出期不得参与候选、父代和类别领先者选择。
- 所有新增行为先写失败测试；手工代码与文档修改使用 `apply_patch`。

---

### Task 1: 校准开发段评分与类别父代池

**Files:**
- Modify: `api/app/factor_strategy_research.py`
- Modify: `api/tests/test_factor_strategy_research.py`

**Interfaces:**
- Produces: `_category_score(summary) -> float`，低样本返回 `0.0`。
- Produces: `run_research(...)["rounds"]`，每轮按类别登记候选 ID。
- Produces: 每个候选的 `research_category` 字段。

- [ ] **Step 1: 写失败测试**

```python
def test_category_score_blocks_low_sample_and_caps_extreme_profit_factor():
    assert _category_score(summary_with_completed(4)) == 0.0
    assert _category_score(summary_with_pf(9000)) == _category_score(summary_with_pf(4))


def test_category_leader_only_uses_its_own_evolution_pool():
    assert select_category_leader("黄金", candidates)["candidate_id"] == "gold_candidate"
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -k 'low_sample or evolution_pool' -q`

Expected: FAIL，因为现有评分不会归零且类别领先者不区分候选来源。

- [ ] **Step 3: 实现最小评分与按类别演化**

```python
# 评分仅在 completed >= MIN_COMPLETED_TRADES 后生效。
# PF 仅用于评分时封顶，期望除以 COSTS["initial_cash"]。
# 每个类别维护自己的 candidates、signatures 和父代，50 轮中每类最多新增 3 个候选。
# 每个候选依然 evaluate_universe 全部 ETF，但 leader 只读取 research_category 相同的候选。
```

- [ ] **Step 4: 运行研究模块测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -q`

Expected: PASS。

### Task 2: 拆分连续留出净值与交易归因

**Files:**
- Modify: `api/app/factor_strategy_research.py`
- Modify: `api/tests/test_factor_strategy_research.py`

**Interfaces:**
- Produces: `_window_statistics(account, detail, start_day)` 中 `rounds` 仅包含留出期新开仓的完整交易。
- Produces: `carry_in_rounds`、`carry_in_completed`，明确记录切分日前开仓、留出期平仓的持仓。

- [ ] **Step 1: 写失败测试**

```python
def test_holdout_keeps_carry_position_in_equity_but_excludes_its_full_trade_pnl():
    window = _window_statistics(account, detail_with_one_carry_trade, "2025-03-01")
    assert window["completed"] == 0
    assert window["carry_in_completed"] == 1
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -k carry_position -q`

Expected: FAIL，因为当前按平仓日收集整笔交易。

- [ ] **Step 3: 实现最小窗口归因修改**

```python
# 保持 daily equity 的 start_day 连续切片逻辑。
# rounds 过滤 entry_date >= start_day；entry_date < start_day <= exit_date 的轮次放入 carry_in_rounds。
```

- [ ] **Step 4: 运行测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -q`

Expected: PASS。

### Task 3: 增加熊市防守观察且不降低发布门槛

**Files:**
- Modify: `api/app/factor_strategy_research.py`
- Modify: `api/tests/test_factor_strategy_research.py`

**Interfaces:**
- Produces: `defense_evidence(summary) -> dict`。
- Produces: 类别领先结果的 `holdout_defense` 与 `stress_defense`。

- [ ] **Step 1: 写失败测试**

```python
def test_bear_market_defense_is_reported_without_removing_release_blockers():
    evidence = defense_evidence(summary_with_strategy_minus_6_and_benchmark_minus_24)
    assert evidence["applicable"] is True
    assert evidence["qualified"] is True
    assert "窗口绝对收益不为正" in _discard_reasons(summary)
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -k bear_market_defense -q`

Expected: FAIL，因为防守观察字段不存在。

- [ ] **Step 3: 实现防守观察字段**

```python
# 基准留出收益 <= -5% 时适用。
# 输出实际在场、超额、下跌捕获率、回撤压缩率和四条件是否共同满足。
# 零在场只标为空仓避险，不得标为策略防守。
# 不更改 _discard_reasons、summary["qualified"] 或生产发布路径。
```

- [ ] **Step 4: 运行测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -q`

Expected: PASS。

### Task 4: 生成校准结果并同步研究文档

**Files:**
- Modify: `scripts/research_factor_strategies.py`
- Modify: `docs/factor-strategy-research-2026-11-27.md`
- Modify: `README.md`
- Modify: `docs/feature-map.md`
- Modify: `docs/single-etf-strategies.md`
- Modify: `docs/superpowers/plans/2026-11-27-category-factor-strategy-research.md`

**Interfaces:**
- Produces: `.local/factor-strategy-2026-11-27/results-50-calibrated.json`。
- Produces: 报告中按类别展示开发段、留出连续净值、留出新开仓交易、跨边界持仓和熊市防守观察。

- [ ] **Step 1: 更新脚本输出说明与研究版本**

Run: `api/.venv/bin/python scripts/research_factor_strategies.py .local/factor-strategy-2026-11-27/input.json .local/factor-strategy-2026-11-27/results-50-calibrated.json --rounds 50`

Expected: 原冻结输入不变，输出文件此前不存在，完成每类别 50 轮校准研究。

- [ ] **Step 2: 依据实际 JSON 更新报告**

报告必须明确：原始 `results-50-screen.json` 未覆盖；`c072` 的百分比笔误已修正；防守证据不等于发布资格；没有候选时不得创建策略、分配或盘前信号。

- [ ] **Step 3: 运行全量验证**

Run: `cd api && .venv/bin/ruff check app tests migrations && .venv/bin/python -m pytest -q`
Run: `cd web && npm run typecheck && npm run build && npm run test:e2e -- --workers=1`
Run: `docker compose --env-file .env.example config --quiet && git diff --check`

Expected: 全部退出码为 0。研究脚本输出、报告数据和版本标识一致。

- [ ] **Step 4: 提交校准变更**

```bash
git add api/app/factor_strategy_research.py api/tests/test_factor_strategy_research.py \
  scripts/research_factor_strategies.py docs/factor-strategy-research-2026-11-27.md \
  README.md docs/feature-map.md docs/single-etf-strategies.md \
  docs/superpowers/specs/2026-11-27-factor-strategy-research-calibration-design.md \
  docs/superpowers/plans/2026-11-27-factor-strategy-research-calibration.md \
  docs/superpowers/plans/2026-11-27-category-factor-strategy-research.md
git commit -m "fix(research): 校准分类因子策略筛选"
```
