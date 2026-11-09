# 策略微观因子实施与验证

按已确认的[指标设计](../specs/2026-11-09-strategy-micro-factors-design.md)执行，
复用当前目录及开发分支，保留此前拖拽配置台未提交改动。

1. 为新增七因子编写手算、预热、严格交叉、分红与无前视测试，
   在 `api/tests/test_strategy_micro_factors.py` 运行失败测试后实现。
2. 在 `api/app/strategy_conditions.py` 扩充目录、校验、计算与诊断，
   在 `strategy_inputs.py` 按来源识别外部依赖，使用同引擎供回测和盘前复用。
3. 在 `strategy_workbench.py` 冻结目录版本及独立诊断，保留旧计算版本和结果，
   通过独立测试库的比较、保存、启用及复算回归验证兼容。
4. 扩充 `web/src/lib/strategyJourney.ts` 参数及预热计算，
   `StrategyFactorBuilder.tsx` 增加分组、双窗口、间隔与事件参数，
   `StrategyComparison.tsx` 展示可展开的诊断，统一说明补齐七因子。
5. 使用 `web/tests/factor-builder.spec.ts` 验证分类默认展开、库内滚动、
   双主题桌面首屏、窄屏／放大、事件配置保存提交及诊断读取。
6. 同步 README、功能地图、单 ETF 使用说明、回测及界面设计；
   执行前端构建／类型检查／浏览器回归、后端 Ruff／完整测试、Compose、链接及差异检查。

测试命令遵循仓库约定：前端 `npm run build`、`npm run typecheck`、
`npx playwright test`；后端 `ruff check app`、`python -m pytest -q`。
集成测试仅连接 `etf_sentinel_test`，不清理开发库。产物截图保存在 `/tmp`。
