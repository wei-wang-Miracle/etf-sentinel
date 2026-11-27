# 分类因子策略研究 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用现有因子冻结全量 ETF 输入，进行 50 轮可解释策略组合研究，并按资产类别输出不可自动发布的研究报告。

**Architecture:** 在 `research_factors.py` 增加与现有因子事件完全同源的逐日真假序列；新的 `factor_strategy_research.py` 以表达式 AST 组合这些真假序列，并通过统一回测引擎结算。独立冻结脚本将本地行情、权益、指数关联和类别元数据写入不可覆盖目录；研究脚本只消费冻结输入并写入本地 JSON，最后将结论摘要整理到文档。

**Tech Stack:** Python 3.14、FastAPI 项目现有 SQLAlchemy 读取层、现有 `simulate` 日频回测引擎、pytest、冻结 JSON。

**Spec:** `docs/superpowers/specs/2026-11-27-category-factor-strategy-research-design.md`

## Global Constraints

- 只使用现有 11 个因子；不得在策略研究中改变指标公式或因子阈值。
- 使用次日开盘、现有成本口径和已核验现金分红；不访问未来数据。
- 候选在全部冻结 ETF 上回测；类别分数按独立跟踪指数等权。
- 50 轮仅搜索策略表达式，统一风险基线不参与搜索。
- 不写数据库、不注册生产策略、不影响每日信号。
- 冻结输出和研究 JSON 写入 `.local/`，不可覆盖；可提交的是代码、测试、说明及最终简报。

---

### Task 1: 暴露既有因子的逐日真值

**Files:**
- Modify: `api/app/research_factors.py`
- Modify: `api/tests/test_research_factors.py`

**Interfaces:**
- Produces: `factor_truth_rows(rows: list[dict], turning: dict[str, str]) -> list[dict]`，每行含 `trade_date` 和 11 个布尔因子值。
- Preserves: `calculate_factor_events(rows, turning)` 的当前可观察事件输出。

- [ ] **Step 1: 写失败测试，覆盖状态持续与事件日语义**

```python
def test_factor_truth_rows_keep_daily_state_while_chart_events_only_mark_entry():
    truth = factor_truth_rows(rows_from_closes([10.0] * 14 + [9.99] * 3), {})
    assert truth[14]["wilder_rsi_oversold"] is True
    assert truth[15]["wilder_rsi_oversold"] is True
    events = calculate_factor_events(rows, {})
    assert [e["trade_date"] for e in events if e["factor_id"] == "wilder_rsi_oversold"] == [rows[14]["trade_date"]]
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_research_factors.py -k truth -q`
Expected: FAIL，因为 `factor_truth_rows` 尚不存在。

- [ ] **Step 3: 抽取因子循环为逐日真假序列**

```python
def factor_truth_rows(rows, turning):
    # 使用现有 Wilder、均线、突破、量比和顶底计算；每个输出行有固定 11 个因子键。
    return [{"trade_date": row["trade_date"], **truth} for row, truth in ...]


def calculate_factor_events(rows, turning):
    truth = factor_truth_rows(rows, turning)
    # 事件因子按当日 true 输出；状态因子只在前一日 false、当日 true 时输出。
```

- [ ] **Step 4: 运行因子完整回归**

Run: `cd api && .venv/bin/python -m pytest tests/test_research_factors.py -q`
Expected: PASS，并确认现有因子目录和图表事件不变。

### Task 2: 实现可解释表达式与统一风险回测

**Files:**
- Create: `api/app/factor_strategy_research.py`
- Create: `api/tests/test_factor_strategy_research.py`

**Interfaces:**
- Consumes: `factor_truth_rows`、`app.backtest.simulate`、`app.strategies.Decision`。
- Produces: `validate_expression(expr)`, `explain_expression(expr)`, `evaluate_expression(expr, truths, index)`, `prepare_factor_strategy(rows, dividends, truth_rows, entry, exit_)`, `evaluate_candidate(item, candidate, start, stop, costs)`。

- [ ] **Step 1: 写表达式和因果性失败测试**

```python
def test_expression_supports_boolean_recent_consecutive_and_sequence_without_future_rows():
    truth = [
        {"trade_date": "2026-01-01", "a": True, "b": False},
        {"trade_date": "2026-01-02", "a": True, "b": True},
    ]
    expr = {"op": "all", "items": [
        {"op": "consecutive", "factor": "a", "days": 2},
        {"op": "after", "first": "a", "then": "b", "within": 2},
    ]}
    assert evaluate_expression(expr, truth, 1) is True
    assert "连续 2 日" in explain_expression(expr)
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -k expression -q`
Expected: FAIL，因为研究模块不存在。

- [ ] **Step 3: 实现表达式 AST 和风险基线**

```python
# 支持 factor/all/any/not/within/consecutive/after；每个叶子必须来自 FACTORS。
# 生成的中文解释不得丢失 NOT、窗口或先后顺序。
# 统一保护：2 ATR 初始止损（不宽于 7%）、盈利 2.5 ATR 后单调 2.5 ATR 跟踪；浮盈达到 5 ATR 后收紧为 1.8 ATR；持有 18 个交易日且浮盈不足 1 ATR 时退出。
# entry 真时目标为 1；exit 真或风险保护命中时目标为 0；决定于收盘、在下一交易日开盘执行。
```

- [ ] **Step 4: 写并运行回测口径测试**

```python
def test_candidate_uses_next_open_and_shared_stop_without_tuning_rule_parameters():
    account = evaluate_candidate(item, candidate, "2025-04-01", "2025-06-30", COSTS)
    assert account["trades"][0]["trade_date"] > account["signal_dates"][0]
    assert account["risk_contract"]["initial_stop_atr"] == 2.0
```

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -q`
Expected: PASS。

### Task 3: 冻结全量 ETF 与类别、独立单位信息

**Files:**
- Create: `api/app/factor_strategy_snapshot.py`
- Create: `scripts/freeze_factor_strategy_research.py`
- Create: `api/tests/test_factor_strategy_snapshot.py`

**Interfaces:**
- Produces: `category_for_code(code) -> str | None`、`build_factor_strategy_item(...) -> tuple[dict, dict]`。
- Frozen item fields: `category`, `independent_key`, `rows`, `actions`, `source`, `coverage`。

- [ ] **Step 1: 写类别和同指数去重失败测试**

```python
def test_category_for_code_separates_gold_and_industry_etfs():
    assert category_for_code("518880") == "黄金"
    assert category_for_code("515880") == "通信设备"
    assert category_for_code("560780") == "半导体材料设备"


def test_independent_key_uses_index_when_mapping_exists():
    item, _ = build_factor_strategy_item(code="510300", indices=["000300.SH"], ...)
    assert item["independent_key"] == "000300.SH"
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_snapshot.py -q`
Expected: FAIL，因为快照模块不存在。

- [ ] **Step 3: 实现冻结转换和脚本**

```python
# 复用 build_snapshot_item 的份额折算归一化和连续交易日校验。
# 查询全部 instruments；有完整本地行情及核验权益的标的进入 input.json。
# 有指数映射时 independent_key=index_code；无映射时 independent_key=instrument_code。
# 未分类标的保留在 coverage，研究报告标记未参与类别排名。
# manifest 固定输入和研究源代码摘要，输出目录必须不存在。
```

- [ ] **Step 4: 运行快照测试及创建真实冻结**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_snapshot.py -q`
Expected: PASS。
Run: `api/.venv/bin/python scripts/freeze_factor_strategy_research.py .local/factor-strategy-2026-11-27`
Expected: 创建不可覆盖的 `input.json` 和 `manifest.json`，不写数据库。

### Task 4: 运行 50 轮类别策略演化和留出验证

**Files:**
- Modify: `api/app/factor_strategy_research.py`
- Create: `scripts/research_factor_strategies.py`
- Modify: `api/tests/test_factor_strategy_research.py`

**Interfaces:**
- Produces: `run_research(universe, rounds=50) -> dict`。
- Output fields: `rounds`, `category_leaders`, `candidates`, `development`, `holdout`, `stress`, `evidence_level`, `discard_reasons`。

- [ ] **Step 1: 写“留出不得参与择优”和“单标的证据”失败测试**

```python
def test_winner_is_selected_from_development_not_better_holdout_candidate(monkeypatch):
    result = run_research(mini_universe, rounds=1)
    assert result["category_leaders"]["测试类别"]["candidate_id"] == "development_winner"


def test_single_independent_unit_is_reported_not_cross_asset_validated():
    report = summarize_category("黄金", accounts_for_one_instrument)
    assert report["evidence_level"] == "单标的证据"
    assert report["cross_unit_pass"] is None
```

- [ ] **Step 2: 运行失败测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -k 'winner or single' -q`
Expected: FAIL，因为 50 轮研究函数不存在。

- [ ] **Step 3: 实现确定性候选演化与分类评分**

```python
# round 1 放入三个透明种子：突破、超跌修复、底部转折。
# 后续 round 使用确定性 seed 生成 add/remove/replace/not-wrap/temporal-wrap/crossover。
# 每个候选运行全部 ETF；类别评分只用开发期，并按 independent_key 等权。
# 最后固定留出期及压力成本只报告，不反馈给候选选择。
# 多独立单位类别记录通过率和单元贡献集中度；单独立单位只输出单标的证据。
```

- [ ] **Step 4: 运行研究模块测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_factor_strategy_research.py -q`
Expected: PASS。

- [ ] **Step 5: 对冻结输入执行 50 轮**

Run: `api/.venv/bin/python scripts/research_factor_strategies.py .local/factor-strategy-2026-11-27 .local/factor-strategy-2026-11-27/results-50.json --rounds 50`
Expected: 输出严格 50 轮记录、全 ETF 结果、类别领先候选和淘汰原因；不得修改冻结输入。

### Task 5: 形成可审查报告并完成回归

**Files:**
- Create: `docs/factor-strategy-research-2026-11-27.md`
- Modify: `README.md`
- Modify: `docs/feature-map.md`
- Modify: `docs/single-etf-strategies.md`

- [ ] **Step 1: 生成按类别的研究结论**

报告必须逐类别列出：ETF 数、独立单位数、证据级别、最佳表达式及中文含义、开发/留出/压力成本核心指标、是否达到研究门槛、未通过原因。没有通过候选时不得给出“建议落地”。

- [ ] **Step 2: 对齐项目说明**

README 与功能地图只说明“离线因子策略研究已完成/进行中”的事实，明确不影响现行算法或信号；策略说明链接最终报告并解释单标的证据含义。

- [ ] **Step 3: 运行完整验证**

Run: `cd api && .venv/bin/ruff check app tests && .venv/bin/python -m pytest -q`
Run: `cd web && npm run typecheck && npm run build && npm run test:e2e -- --workers=1`
Run: `docker compose --env-file .env.example config --quiet && git diff --check`
Expected: 全部命令退出码为 0；报告中的轮数、冻结摘要和结果 JSON 可相互核对。

- [ ] **Step 4: 提交研究代码和报告**

```bash
git add api/app/research_factors.py api/app/factor_strategy_research.py \
  api/app/factor_strategy_snapshot.py scripts/freeze_factor_strategy_research.py \
  scripts/research_factor_strategies.py api/tests/test_research_factors.py \
  api/tests/test_factor_strategy_research.py api/tests/test_factor_strategy_snapshot.py \
  docs/factor-strategy-research-2026-11-27.md README.md docs/feature-map.md \
  docs/single-etf-strategies.md docs/superpowers/specs/2026-11-27-category-factor-strategy-research-design.md \
  docs/superpowers/plans/2026-11-27-category-factor-strategy-research.md
git commit -m "feat(research): 增加分类因子策略研究"
```

## Self-Review

- 规格覆盖：当前因子组合、逻辑与时间关系、全量 ETF、类别去重、单标的类别、50 轮、留出验证、结果报告和“未通过即不落地”均有对应任务。
- 占位检查：计划不使用 TODO、待定或“适当处理”占位；每项代码任务给出函数名、字段与测试命令。
- 类型一致性：`factor_truth_rows` 的逐日布尔输出由表达式引擎消费；`run_research` 消费冻结输入并返回报告；冻结脚本与研究脚本均以不可覆盖文件作为边界。
