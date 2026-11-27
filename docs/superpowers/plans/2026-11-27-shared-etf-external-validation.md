# Shared ETF External Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 从本地已核验行情生成带份额折算标准化的研究冻结输入，运行不改参数的三只跨资产 ETF 固定先验验证。

**Architecture:** 新增纯函数模块完成研究专用的份额口径转换和输入完整性校验；新增冻结脚本只读本地数据库并写入新目录。既有 `research_shared_etf.py` 继续只读取冻结文件，利用其已有迁移标的评估路径输出报告，不接入任何生产策略。

**Tech Stack:** Python 3.12+、SQLAlchemy、pytest、ruff、PostgreSQL 本地只读查询、JSON SHA-256 冻结输入。

**Spec:** `docs/superpowers/specs/2026-11-27-shared-etf-external-validation-design.md`

## Global Constraints

- 所有新增说明、注释和用户可见文本使用中文。
- 不改生产行情库、算法绑定、盘前信号、算法注册或固定先验中心参数。
- 冻结输入只读本地数据库；目标目录存在即失败，不覆盖历史研究。
- 份额折算转换只存在于研究冻结输入，必须保留原始折算证据和转换摘要。
- 当前本地覆盖始于 2024 年，报告不得称为 2019—2026 年长周期验证或真正盲测。

---

### Task 1: 研究快照的份额标准化

**Files:**
- Create: `api/app/shared_etf_snapshot.py`
- Test: `api/tests/test_shared_etf_snapshot.py`

**Interfaces:**
- Produces: `normalize_split_history(rows, actions) -> (rows, actions, conversion)`。
- Produces: `validate_snapshot_rows(rows, actions)`，拒绝缺日、价格关系异常、零成交量和非空折算事件。

- [x] **Step 1: 写入失败测试**

覆盖 1:2 合并、历史分红同步缩放、已标准化动作不再含折算事件，以及缺日或异常 OHLCV 拒绝。

- [x] **Step 2: 运行定向测试，确认当前不存在实现**

Run: `cd api && .venv/bin/python -m pytest tests/test_shared_etf_snapshot.py -q`

Expected: FAIL，模块尚不存在。

- [x] **Step 3: 实现最小转换与校验**

只复用既有份额倍率定义，按最终份额口径缩放价格、成交量和历史每份现金分红；不修改生产行情数据或回测引擎。

- [x] **Step 4: 重跑定向测试**

Run: `cd api && .venv/bin/python -m pytest tests/test_shared_etf_snapshot.py -q`

Expected: PASS。

### Task 2: 本地只读冻结脚本

**Files:**
- Create: `scripts/freeze_shared_etf.py`
- Modify: `api/tests/test_shared_etf_snapshot.py`

**Interfaces:**
- Consumes: 本地 `Candle`、`BacktestSource`、`Instrument` 与 `InstrumentIndexLink`。
- Produces: 新目录中的 `input.json`、`manifest.json`，兼容 `scripts/research_shared_etf.py`。

- [x] **Step 1: 写入失败测试**

覆盖 11 个固定代码、宽基与迁移标的角色、输入包含指数关联、manifest 记录摘要和已有目录拒绝覆盖。

- [x] **Step 2: 运行定向测试，确认失败**

Run: `cd api && .venv/bin/python -m pytest tests/test_shared_etf_snapshot.py -q`

Expected: FAIL，冻结组装函数尚不存在。

- [x] **Step 3: 实现冻结组装与命令行入口**

读取本地库、校验完整性、调用 Task 1 转换、写入不可覆盖目录。脚本不得访问网络或写入数据库。

- [x] **Step 4: 运行定向测试和生成冻结输入**

Run: `cd api && .venv/bin/python -m pytest tests/test_shared_etf_snapshot.py -q`

Run: `api/.venv/bin/python scripts/freeze_shared_etf.py .local/shared-etf-external-2026-11-27`

Expected: PASS；目录包含经 SHA-256 记录的输入和 manifest。

### Task 3: 外部迁移实证与文档口径

**Files:**
- Modify: `docs/shared-etf-walk-forward.md`
- Modify: `README.md`
- Modify: `docs/feature-map.md`

**Interfaces:**
- Consumes: Task 2 新冻结目录。
- Produces: 不覆盖的新 JSON 报告，包含三只迁移标的实际评估结果与覆盖限制。

- [x] **Step 1: 运行固定先验研究**

Run: `api/.venv/bin/python scripts/research_shared_etf.py .local/shared-etf-external-2026-11-27 .local/shared-etf-external-validation-2026-11-27.json`

- [x] **Step 2: 校验结果**

确认三只迁移标的均为“已评估”，中心规则完全等于既有固定先验规则，报告仍为 `eligible_for_release: false`。

- [x] **Step 3: 更新文档**

记录实际评估区间、跨资产结果、未通过或未达到发布条件的事实，以及尚未完成的 2019 年长周期验证。

### Task 4: 完整核验

**Files:**
- Modify: 本计划涉及的所有新增或更新文件。

- [x] **Step 1: 静态检查与全量后端测试**

Run: `cd api && .venv/bin/ruff check app tests ../scripts/freeze_shared_etf.py ../scripts/research_shared_etf.py`

Run: `cd api && .venv/bin/python -m pytest -q -rs`

- [x] **Step 2: 编排、文档与差异检查**

Run: `docker compose --env-file .env.example config --quiet`

Run: `git diff --check`

- [x] **Step 3: 确认生产边界**

核对差异未触及迁移、生产数据写入、算法注册、策略绑定、盘前信号与旧冻结文件。
