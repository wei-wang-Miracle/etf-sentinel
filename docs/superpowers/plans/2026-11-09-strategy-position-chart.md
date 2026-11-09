# 模拟仓位副图实施计划

目标是落实已确认的[仓位设计](../specs/2026-11-09-strategy-position-chart-design.md)，
在当前项目目录与分支实现，保留既有未提交功能；不新增依赖或后端接口。

1. 在 `web/tests/position-chart.spec.ts` 增加隔离比较账本和失败测试：
   满／半仓、清仓、缺失日期、切换策略、联动缩放、悬停与键盘读数；
   使用真实 ECharts 实例验证副图数据与固定轴，回归普通行情成交量。
2. 在 `web/src/lib/backtests.ts` 补充已有账本字段
   `market_value?: string`；`KLine.tsx` 接收 `positions?: DailyAccount[]`，
   按交易日期对齐到现有日 K 日期，比例乘 100；缺失为 null，零值有效。
   仓位模式第二轴使用 `min: 0, max: 100`，中性色柱。
3. `StrategyComparison.tsx` 传入所选 `track.account.daily`，明确图注的
   每日收盘口径；更新悬停、无账本状态和键盘读数。只修改此次必要展示。
4. 运行 `npx playwright test tests/position-chart.spec.ts` 完成失败到通过；
   检查截图后执行 `npm run build`、`npm run typecheck`、`npx playwright test`。
5. 同步 README、功能地图、单 ETF 与回测说明和验收记录；检查本地文档链接、
   `docker compose --env-file .env.example config --quiet`、`git diff --check`。


## 执行结果

五步均已完成。新增六项仓位图表测试先验证旧副图为成交量，再接入仓位账本；
完整66项浏览器回归通过，构建、类型检查、Compose、本地链接与差异检查通过。
独立代码审查未发现待修复问题。远程拉取因 GitHub 443 连接超时失败，
使用当前项目目录的新分支继续开发，保留既有未提交改动；没有部署或操作生产环境。
