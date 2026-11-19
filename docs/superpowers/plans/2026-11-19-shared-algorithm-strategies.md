# 共享算法策略实施计划

1. 在 `api/tests/test_algorithm_templates.py` 增加跨标的快照和严格比较请求检查。再修改 `api/app/algorithm_templates.py` 与 `api/app/strategy_workbench.py`，接通算法标识多选、统一快照、固定成本及既有复算。
2. 在 `api/tests/test_strategy_workbench_database.py` 验证回测与绑定分离、跨标的绑定、重复保存与启停，使用 `saved_strategies` 增加 ETF 与模板身份唯一约束，以可追踪迁移落库。
3. 在 `web/tests/strategy-template.spec.ts` 保护算法库入口、统一比较、保存和启用。替换策略编辑器，复用现有回测图表，并让持仓与日 K 入口进入算法回测。
4. 更新 README、功能地图和回测说明；运行 Python 检查、独立库迁移与集成测试、前端构建和浏览器回归。
