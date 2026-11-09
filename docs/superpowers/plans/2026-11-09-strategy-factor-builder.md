# 创建策略因子配置实施计划

本文记录拖拽配置台初版范围。后续十七类来源分组、规则参数扩展与触发诊断见
[微观因子设计](../specs/2026-11-09-strategy-micro-factors-design.md)。

按[已确认设计](../specs/2026-11-09-strategy-factor-builder-design.md)在当前分支实施。
目标是完整指标库、拖拽复制、买卖并排编辑及桌面一屏配置。
技术栈沿用 React、TypeScript、CSS、HTML 拖放与原生 dialog；不增加依赖或接口。

## 文件职责

本次将规则配置从编辑器中拆为一个组件，保持比较、保存及启用流程集中在原编辑器。

- 新增 `web/src/components/StrategyFactorBuilder.tsx`：指标库、买卖条件、说明弹层。
- 新增 `web/src/styles/strategy-factor-builder.css`：配置台与响应式布局。
- 修改 `web/src/components/StrategyEditor.tsx`：接入配置台，保留草稿及规则失效逻辑。
- 修改 `web/src/pages/MyStrategies.tsx`：压缩创建页重复标题与控件留白。
- 修改 `web/tests/fixtures.ts`：补全隔离测试目录中的十类指标。
- 新增 `web/tests/factor-builder.spec.ts`：拖拽、参数、限制、说明、兼容与视口测试。
- 修改 `web/tests/strategy.spec.ts`：将旧常驻说明测试调整为已确认的弹层交互。
- 更新 README、功能地图、单 ETF 使用说明及受影响的设计说明。

## 任务一：先建立可失败的浏览器验收

使用现有 Playwright 与隔离 API，避免接触真实账户。

- [x] 为十类指标补齐中文名、单位、窗口与证据类别测试资料。
- [x] 测试完整指标库默认可见，拖入买入组仅新增买入条件，源指标保留。
- [x] 测试点击和键盘添加、参数修改、草稿恢复及提交原有 all／any 规则结构。
- [x] 测试取消拖放不改规则、每组 1 至 20 条限制与两组独立。
- [x] 测试缺失数据、恐贪类别必填及说明关闭后的焦点返回。
- [x] 测试两种桌面视口、双主题、390 像素和 200% 缩放。
- [x] 运行 `cd web && npm run test:e2e -- factor-builder.spec.ts --workers=1`，
  确认失败原因是缺少指标库与拖放配置台。

关键断言使用真实浏览器拖放和请求内容，例如：

```typescript
await source.dragTo(page.getByRole("group", { name: "什么时候买", exact: true }));
await expect(page.getByRole("article", { name: "买入条件2", exact: true })).toBeVisible();
expect(submitted.current.rule.buy.mode).toBe("any");
```

## 任务二：实现规则配置台

组件的输入为现有规则、目录、数据覆盖及禁用状态；修改通过原更新函数回传。

- [x] 用目录驱动完整指标库，提供拖拽以及分别加入买卖的按钮。
- [x] 拖放只接受当前指标库拖出的已注册指标，组外放开不修改规则。
- [x] 复用现有窗口、比较符、阈值、类别及最少条件约束，补齐最多二十条限制。
- [x] 使用受控规则更新，继续通过 `updateRule` 使旧比较失效并触发原草稿保存。
- [x] 用原生 dialog 展示现有指标解释，支持 Escape、关闭及焦点返回。
- [x] 移除本次替换的旧条件组件与其专用样式，保持比较和保存界面行为。
- [x] 运行任务一测试，修正实际交互直至通过。

## 任务三：布局与流程回归

使用剩余视口高度承载配置台；空间不足及放大时允许自然重排。

- [x] 创建页采用紧凑对象头和阶段导航，顶部放名称、模板与投入比例。
- [x] 桌面三栏展示指标库、买入组、卖出组；长条件区内部滚动。
- [x] 操作栏保持可见，规则摘要可展开；重复口径提示统一收进左栏说明，不推移布局。
- [x] 窄屏纵向排列，点击按钮能完成全部添加操作，无页面横向溢出。
- [x] 比较记录入口保持可达；已有草稿、版本修改、比较失效及保存启用回归通过。
- [x] 查看隔离数据生成的桌面双主题及窄屏截图，修正遮挡、裁切和过密布局。

## 任务四：文档与交付检查

同步当前能力描述，不把未验证链路写成完成。

- [x] 更新 README、功能地图、单 ETF 使用说明和受影响的设计约定。
- [x] 在 `web/` 运行 `npm run build`、`npm run typecheck` 和 `npm run test:e2e`。
- [x] 根目录运行 `docker compose --env-file .env.example config --quiet`。
- [x] 检查改动文档的本地链接和 `git diff --check`，报告实际执行结果。

## 实际验证结果

前端构建、类型检查、58项隔离浏览器测试、Compose配置和文档链接检查通过。
新增测试先验证旧界面缺少指标库和统一说明入口，再实现对应交互。
只读代码与增量审查未发现阻断问题，截图确认紧凑布局及条件区域不重叠。
具体范围见[验收记录](../../design/frontend-validation.md#2026-11-09-因子配置台增量验收)。
