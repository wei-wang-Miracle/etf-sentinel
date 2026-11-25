# Unified Turning Factor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让行情 K 线、算法模板回测和盘前信号共用服务端参数化顶底确认因子。

**Architecture:** 将现有六类研究的参数迁入 `algorithm_templates.py`，保留一份因果事件引擎。算法模板快照携带当前 ETF 的顶底参数，策略执行从快照调用该引擎；行情接口从相同参数注册表调用。前端删除本地计算与来源切换，仅渲染接口事件。

**Tech Stack:** Python 3.12、FastAPI、pytest；React、TypeScript、Vite、Playwright。

**Spec:** `docs/superpowers/specs/2026-11-25-unified-turning-factor-design.md`

## Global Constraints

- 顶底事件按交易日正序计算，确认日收盘生成，策略只在下一交易日开盘执行。
- ETF 可使用不同固定参数模板；指标公式、事件状态机和回测执行口径必须共用。
- 不新增用户配置、数据库表或可选历史版本。
- 不覆盖当前工作区已有未提交改动。

---

### Task 1: 服务端顶底参数与事件引擎

**Files:**
- Modify: `api/app/algorithm_templates.py`
- Test: `api/tests/test_algorithm_templates.py`

**Interfaces:**
- Produces: `turning_profile(instrument_code)`，返回冻结的分类名称与参数。
- Produces: `turning_events(rows, dividends, options)`，依据该参数计算确认事件。

- [x] 写入“同引擎、不同参数”和“顶部高点回落”失败测试。
- [x] 运行 `pytest tests/test_algorithm_templates.py -q`，确认当前实现不能满足新契约。
- [x] 迁移分类参数到服务端，扩展事件引擎的顶部独立窗口和高点回落路径。
- [x] 再次运行同一测试，确认事件前缀稳定且不同 ETF 参数由同一注册表解析。

### Task 2: 模板快照、回测与行情接口统一

**Files:**
- Modify: `api/app/algorithm_templates.py`
- Modify: `api/app/main.py`
- Test: `api/tests/test_algorithm_templates.py`
- Test: `api/tests/test_strategy_workbench_database.py`

**Interfaces:**
- Consumes: `turning_profile()` 和 `turning_events()`。
- Produces: 所有 `template_snapshot()` 都包含 ETF 绑定的顶底参数快照。

- [x] 写入“模板与行情使用同一参数”的失败测试。
- [x] 让 `prepare_template()` 从模板快照调用顶底事件，引擎不得从客户端接收参数。
- [x] 让行情接口从同一 ETF 参数注册表调用顶底事件。
- [x] 运行模板与独立数据库测试；无独立测试库时记录跳过原因。

### Task 3: 行情页移除第二套算法

**Files:**
- Modify: `web/src/components/EtfTurningChart.tsx`
- Modify: `web/src/pages/Market.tsx`
- Modify: `web/src/pages/ResearchObject.tsx`
- Delete: `web/src/lib/turningPoints.ts`
- Delete: `web/src/lib/turningCategories.ts`
- Delete: `web/tests/turning-points.spec.ts`
- Delete: `web/tests/turning-categories.spec.ts`
- Modify: `web/tests/turning-chart.spec.ts`

**Interfaces:**
- Consumes: `/candles/{code}/turning-events`。
- Produces: 同一份顶底事件的独立显示开关与错误／截止日状态。

- [x] 改写浏览器测试，先断言页面不再存在“顶底来源”控件，且标记来自接口事件。
- [x] 移除前端分类参数与本地顶底计算，保留事件显示、开关、真实操作叠加和图表缩放。
- [x] 运行相关 Playwright 用例、`npm run typecheck` 与 `npm run build`。

### Task 4: 文档与最终验证

**Files:**
- Modify: `README.md`
- Modify: `docs/turning-points.md`
- Modify: `docs/single-etf-strategies.md`
- Modify: `docs/feature-map.md`

- [x] 更新统一因子、参数模板、行情展示和回测边界说明。
- [x] 运行后端静态检查、测试、前端构建和 Compose 配置检查。
- [x] 运行 `git diff --check`，逐项对照设计验收条件。
