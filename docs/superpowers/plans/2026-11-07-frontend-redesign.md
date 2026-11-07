# 前端研究案卷实施计划

用户已于2026-11-07确认按 [DESIGN.md](../../../DESIGN.md) 实施。
本计划由当前代理执行，策略工作区使用子代理完成并分别审查需求符合性和代码质量。
继续使用当前目录与开发分支，不新建工作区，不自动提交或部署。

**目标：**落实对象连续性、图表优先、三阶段策略与双主题统一体验。
**架构：**沿用 React、CSS变量与 ECharts，复用现有 API 和业务引擎；
路由参数保存对象与任务位置，共享 Tab 和返回链接统一导航行为。
**验证：**Playwright 使用明确标注的接口测试数据隔离写入；现有本地数据只读走查。

## 1. 测试基础与导航

回归测试先复现现状，再实施修改；不针对纯样式逐条编写镜像测试。

- [x] 增加 `web/playwright.config.ts`、`web/tests/fixtures.ts` 和
  `web/tests/navigation.spec.ts`。覆盖512100跨导航保持、空持仓不回退、
  账户失败不阻断全部ETF、分类刷新及键盘Tab。
- [x] 执行 `npm run test:e2e -- navigation.spec.ts`，确认上述缺陷真实失败。
- [x] 修改 `web/src/lib/research.ts` 的查询更新，允许显式 push/replace，
  区分导航与输入调整；增加 `web/src/lib/navigation.ts` 统一内部返回链接。
- [x] 修改 `web/src/App.tsx` 保留ETF与日期上下文，主导航显示文字，小屏释放侧栏。
- [x] 修改 `DataManagement.tsx`、`Jobs.tsx`，将分类与任务写入URL并支持返回原任务。
- [x] 重新执行导航回归并确认通过。

核心链接的行为目标如下：

```text
?page=etfs&code=512100&detail=overview&start=…&end=…
  → ?page=strategies&code=512100&start=…&end=…
  → ?page=data&code=512100&manage=jobs&task=etf&return_to=…
```

## 2. ETF详情、数据与信号

文件范围为 `MyEtfs.tsx`、`ResearchObject.tsx`、`EtfReview.tsx`、
`DailySignals.tsx`、`Compare.tsx`，新增共享 `Tabs.tsx` 和必要的状态／日期读数组件。

- [x] 用独立请求状态区分标的、持仓和版本读取，持仓空集合保持空，不伪装零仓。
- [x] 列表范围和搜索进入URL；ETF详情只保留一个h1、一个可操作对象选择器。
- [x] 图表维度收敛为行情、关联估值、国家队和市场情绪，移出占位与重复策略入口。
- [x] 真实操作保留核算资格与确认依据，研究基线改为次级展开区。
- [x] 首页与策略页显示紧凑信号摘要，ETF信号页保留完整核对，分开适用与历史计划。
- [x] 信号区分无版本、待运行、任务关闭、阻断、数量未知；不新增交易日推断。
- [x] 数据修复链接定位具体任务或账户区，并安全返回原对象和草稿。
- [x] 对比对象选择折叠，不隐藏失败对象，移除未实现因子入口。
- [x] 添加并执行 `web/tests/research.spec.ts`，覆盖零值、未知、历史信号和图表读数。

## 3. 策略工作区（独立子任务）

主修改 `MyStrategies.tsx`、`StrategyEditor.tsx`、`StrategyComparison.tsx`；
可拆出 `StrategyConditions.tsx`，样式集中在 `strategy-journey.css`。
测试为 `web/tests/strategy.spec.ts`，由子代理先添加失败测试。

- [x] 无对象时显式选ETF；保存版本只读，修改保存为新版。
- [x] 将工作区改为配置规则、回测比较、保存与启用三个真实阶段，保留URL阶段与草稿。
- [x] 帮助在宽屏稳定侧区，窄屏主动展开；保留十类指标的完整解释。
- [x] 统一比较假设常驻，指标用矩阵，失败对象保留；真实收益独立折叠。
- [x] 规则或成本变化使旧结果失效，保存与启用不可用；历史比较只读。
- [x] 保存并启用使用显式影响确认；保存成功启用失败仅重试同版本。
- [x] 草稿保存状态准确；已有本地／服务端草稿读取保护不得回退。
- [x] 执行策略测试与 `npm run typecheck`，修复后分别进行规格与质量审查。

## 4. 双主题、图表与响应式

保持现有语义变量，收敛 `tokens.css`、`global.css` 和新增 `research-workspace.css`。
图表修改 `lib/chart.ts`、`KLine.tsx`、`ResearchChart.tsx`、`ValuationChart.tsx`，
必要时复用已有情绪图，不改变数据计算。

- [x] 采用DESIGN中的字体、颜色、字号、控件及中性选中态；避免覆盖层叠冲突。
- [x] 桌面侧栏208px；小屏文字导航，正文14px、辅助13px、图表标签至少12px。
- [x] 对比图表使用独立六色，不借用行情和情绪色；同对象曲线身份稳定。
- [x] 图表提供键盘日期读数，保留缺失断线、缩放和来源。
- [x] 密集真实标记在行情页默认不叠加；复盘页保持可追溯。
- [x] 浏览器验收1440、1024、768、390px、双主题和200%缩放；
  常规行情图顶端桌面≤360px、390px屏≤640px，窄屏图宽≥350px。

## 5. 文档与交付

更新文档中的现状和契约，不把浏览器测试数据当真实投资结果。

- [x] 更新 README、功能地图、设计契约、单ETF使用说明及本次设计状态。
- [x] 运行 `npm run test:e2e`、`npm run build`、`npm run typecheck`。
- [x] 运行 `docker compose --env-file .env.example config --quiet`。
- [x] 检查修改文档链接及 `git diff --check`，进行最终独立代码审查并修复问题。
- [x] 交付实现结果、测试证据及实际未验证项，不执行部署。

## 完成记录

本轮实施和必要回归已完成，详细证据及未验证边界见[实施验收记录](../../design/frontend-validation.md)。
未提交、推送或部署。
