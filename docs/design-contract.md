---
version: alpha
name: "Ledger Terminal"
description: "个人宽基 ETF 量化研究平台的设计契约：暗色优先、数据密集、低装饰、可审计；分离行情方向、情绪与系统状态三套颜色语义。"
colors:
  primary: "#FF8A72"
  on-primary: "#211713"
  primary-hover: "#FFA28F"
  primary-soft: "#30221F"
  canvas: "#0B0E14"
  surface: "#11151D"
  surface-elevated: "#161B24"
  surface-hover: "#1B2230"
  ink: "#E6EAF2"
  ink-muted: "#8A94A6"
  ink-subtle: "#5C6678"
  border: "#232A36"
  border-strong: "#344052"
  market-up: "#F04438"
  market-down: "#12B76A"
  sentiment-fear: "#38BDF8"
  sentiment-greed: "#F59E0B"
  status-success: "#22C55E"
  status-warning: "#F59E0B"
  status-danger: "#F04438"
  status-info: "#38BDF8"
  chart-1: "#5B8CFF"
  chart-2: "#A78BFA"
  chart-3: "#22D3EE"
  chart-4: "#F59E0B"
  chart-5: "#F472B6"
  chart-6: "#94A3B8"
  focus-ring: "#FFAA94"
typography:
  display-lg:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 32px
    fontWeight: 600
    lineHeight: 40px
    letterSpacing: 0px
  heading-lg:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 24px
    fontWeight: 600
    lineHeight: 32px
    letterSpacing: 0px
  heading-md:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 28px
    letterSpacing: 0px
  heading-sm:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 16px
    fontWeight: 600
    lineHeight: 24px
    letterSpacing: 0px
  body-md:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 22px
    letterSpacing: 0px
  body-sm:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 20px
    letterSpacing: 0px
  caption:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 12px
    fontWeight: 500
    lineHeight: 16px
    letterSpacing: 0px
  mono-lg:
    fontFamily: "JetBrains Mono, SF Mono, Roboto Mono, monospace"
    fontSize: 20px
    fontWeight: 600
    lineHeight: 28px
    letterSpacing: 0px
  mono-md:
    fontFamily: "JetBrains Mono, SF Mono, Roboto Mono, monospace"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 20px
    letterSpacing: 0px
  button-md:
    fontFamily: "Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    fontSize: 13px
    fontWeight: 600
    lineHeight: 20px
    letterSpacing: 0px
rounded:
  none: 0px
  xs: 2px
  sm: 4px
  md: 6px
  lg: 8px
  xl: 12px
  full: 9999px
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  section: 48px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    padding: "0px 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    padding: "0px 16px"
    height: "40px"
  button-primary-disabled:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.ink-subtle}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    padding: "0px 16px"
    height: "40px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.button-md}"
    rounded: "{rounded.md}"
    padding: "0px 16px"
    height: "40px"
  text-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: "0px 12px"
    height: "36px"
  text-input-focused:
    backgroundColor: "{colors.surface-elevated}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: "0px 12px"
    height: "36px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: "16px"
  table-header:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.none}"
    padding: "0px 12px"
    height: "36px"
  table-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    padding: "0px 12px"
    height: "36px"
  table-row-selected:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    padding: "0px 12px"
    height: "36px"
  badge-neutral:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 8px"
    height: "22px"
  badge-success:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.status-success}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 8px"
    height: "22px"
  badge-warning:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.status-warning}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 8px"
    height: "22px"
  badge-danger:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.status-danger}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 8px"
    height: "22px"
  badge-info:
    backgroundColor: "{colors.surface-hover}"
    textColor: "{colors.status-info}"
    typography: "{typography.caption}"
    rounded: "{rounded.full}"
    padding: "4px 8px"
    height: "22px"
  nav-item:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
    padding: "0px 12px"
    height: "40px"
  nav-item-active:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
    padding: "0px 12px"
    height: "40px"
  metric-value:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.mono-lg}"
    rounded: "{rounded.none}"
    padding: "0px"
    height: "28px"
  metric-label:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.caption}"
    rounded: "{rounded.none}"
    padding: "0px"
    height: "16px"
  signal-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: "16px"
---

# Ledger Terminal — 设计契约

## Overview

这是一个**个人量化研究终端**，不是营销网站，也不是通用后台模板。

它应该像一张安静、精确、可审计的研究工作台：数据是主角，界面负责把数据的层次、来源和时间讲清楚。视觉上参考 Linear 的暗色秩序、Stripe 的数据表密度、TradingView 的图表可读性，但比它们更克制。

三条设计原则：

1. **数据优先**：屏幕面积优先给图表和表格；装饰、插画、渐变一律让位。
2. **语义分离**：行情方向、情绪、系统状态是三套独立颜色，互不借用，避免“红色到底是涨还是错”。
3. **低装饰、高密度**：1px 细边框、分层表面、少量圆角；不用玻璃拟态、发光、装饰性渐变。

默认暗色，支持亮色。中文优先，数字用等宽字体并启用 `tabular-nums`。

## Colors

### 语义域

颜色按用途分成五组，**不允许跨域借用**：

| 域 | Token | 用途 | 禁止 |
|---|---|---|---|
| 品牌/操作 | `primary`、`primary-hover`、`primary-soft` | 主按钮、选中态、链接、焦点 | 不用来表示涨跌或情绪 |
| 行情方向 | `market-up`（红）、`market-down`（绿） | 涨跌、K 线、收益正负 | 不用来表示成功/失败或贪婪/恐惧 |
| 情绪 | `sentiment-fear`（蓝）、`sentiment-greed`（琥珀） | FGI、恐惧贪婪区间、因子贡献正负 | 不用红绿表示情绪，避免和涨跌冲突 |
| 系统状态 | `status-success/warning/danger/info` | 任务状态、校验结果、告警 | 必须同时有图标或文字，不能只靠颜色 |
| 图表序列 | `chart-1`…`chart-6` | 多序列折线、基准、因子 | 不超过 6 条；不用于行情涨跌 |

### 操作强调与行情、情绪分离

A 股习惯红涨绿跌。如果再拿红色表示“贪婪”、绿色表示“恐惧”，同一屏会出现两套红绿语义。因此：

- **操作主色用朱红/珊瑚色**，只承担按钮、导航和选中；不能据此判断涨跌。
  数值涨跌仍只使用 `market-up/down`，情绪仍只使用 `sentiment-*`。
- **恐惧用蓝、贪婪用琥珀**，靠“冷暖”表达情绪，靠文字表达区间。
- **中性/持平用 `ink-muted`**，不额外造一个灰色 token。
- **数据新鲜度复用系统状态色**：fresh → `status-success`，stale → `status-warning`，missing → `status-danger`。

### 表面层级

```text
canvas (#0B0E14) → surface (#11151D) → surface-elevated (#161B24) → surface-hover (#1B2230)
```

页面背景用 `canvas`，卡片用 `surface`，浮层用 `surface-elevated`，悬停用 `surface-hover`。层级只靠背景差和 1px 边框，不靠重阴影。

### 软背景

状态徽标、提示条的浅色底不使用新 hex，统一用：

```css
background: color-mix(in srgb, var(--color-<semantic>) 14%, transparent);
```

这样新增语义色时不需要再补一个 `-soft` token。

### 对比度

- 正文与背景 ≥ 4.5:1；大字号（≥ 24px 或 18px 加粗）≥ 3:1。
- `market-up` / `market-down` 放在 `surface` 上必须实测；不要凭肉眼判断。
- 任何“只靠颜色”的表达都视为无障碍缺陷。

## Typography

### 字体栈

```text
标题:  Songti SC, Noto Serif CJK SC, STSong, SimSun, Georgia, serif
UI:    Inter, PingFang SC, Source Han Sans SC, Microsoft YaHei, sans-serif
数字:  JetBrains Mono, SF Mono, Roboto Mono, monospace
```

- 中文正文 14px，密集表格 13px，说明文字 12px。
- 所有价格、收益率、分位、代码、日期使用 `mono-*` 并启用 `font-variant-numeric: tabular-nums`。
- 不使用斜体；不使用字重 300 以下；全站最多 400 / 500 / 600 三档。
- 中文不额外加字距；英文标题字距保持 0。

### 层级

| Token | 字号/行高 | 字重 | 用途 |
|---|---|---|---|
| `display-lg` | 32/40 | 600 | 页面主指标（极少用） |
| `heading-lg` | 24/32 | 600 | 页面标题 |
| `heading-md` | 20/28 | 600 | 卡片组标题 |
| `heading-sm` | 16/24 | 600 | 卡片标题 |
| `body-md` | 14/22 | 400 | 正文、说明 |
| `body-sm` | 13/20 | 400 | 表格、密集列表 |
| `caption` | 12/16 | 500 | 标签、来源、时间戳 |
| `mono-lg` | 20/28 | 600 | 大数字、净值 |
| `mono-md` | 13/20 | 500 | 表格数字、代码 |
| `button-md` | 13/20 | 600 | 按钮 |

### 数字格式

- 收益率：两位小数，带符号，例如 `+1.24%`。
- 分位/分数：一位小数，例如 `69.5`。
- 比率：两位小数，例如 `4.57`。
- 日期：`YYYY-MM-DD`；时间：`HH:mm`。
- 代码：等宽大写，例如 `000300.SH`、`510300`。
- 表格数字右对齐；文本左对齐；状态居中。

## Layout

### App Shell

```text
┌────────────── 240px ──────────────┬──────────────────────────────┐
│ Logo / 导航                        │ TopBar 56px                  │
│                                   ├──────────────────────────────┤
│ 数据收集                           │ Page header                  │
│ 数据展示                           │                              │
│ 策略配置                           │ Content, padding 24px        │
│ 策略回测                           │                              │
│ 买卖信号                           │                              │
│ 持仓与日志                         │                              │
└───────────────────────────────────┴──────────────────────────────┘
```

- 侧栏 240px，可折叠到 64px（仅图标）。
- 顶栏 56px：市场日期、数据新鲜度、同步状态、全局搜索、主题切换。
- 内容区不留最大宽度，数据表可以铺满；页面内边距 24px。
- 12 列网格，列间距 16px；卡片跨 3/4/6/8/12 列。

### 密度

- 表格默认 **compact**：行高 36px；阅读型页面可切换 comfort：44px。
- 表格头吸顶；首列在横向滚动时吸左；数字列右对齐。
- 图表标准高度 320px；K 线 480px；缩略 sparkline 48px。
- 卡片内边距 16px；卡片间距 16px；页面区块间距 24px。

### 页面头部模式

所有页面统一：

```text
[页面标题]        [市场日期] [数据新鲜度]        [次要操作] [主操作]
[一句话说明，可选]
```

主操作只有一个；危险操作永远不放在主操作位置。

## Elevation & Depth

| 层级 | 用途 | 表现 |
|---|---|---|
| 0 | 页面背景 | `canvas` |
| 1 | 卡片 | `surface` + 1px `border` |
| 2 | 下拉/浮层 | `surface-elevated` + 1px `border` + `0 12px 32px rgba(0,0,0,.45)` |
| 3 | 模态 | `surface-elevated` + 更强阴影 + 背景遮罩 `rgba(0,0,0,.6)` |

- 暗色下不用大面积阴影表达层级，优先用表面色差和边框。
- 除 `focus-ring` 外不使用发光效果。
- 禁止玻璃拟态、渐变按钮、彩色投影。

## Shapes

- 卡片 8px，按钮 6px，输入框 4px，标签/徽标全圆角，表格 0。
- 边框统一 1px；不要双线、不要 2px 装饰边。
- 不使用大圆角容器（> 12px）包裹数据表。
- 分割线用 `border`，悬停态用 `surface-hover`，不额外加阴影。

## Components

### AppSidebar

- 240px / 折叠 64px；背景 `canvas`；右侧 1px `border`。
- 导航项 `nav-item`；激活项 `nav-item-active`，左侧 2px `primary` 指示条。
- 底部显示版本号与数据源状态点。

### TopBar

- 56px；左侧面包屑，中间留空，右侧市场日期、数据新鲜度、同步状态、主题切换。
- 数据新鲜度使用 `badge-success/warning/danger` + 文本，不只用圆点。
- 同步进行中显示旋转图标和“同步中”，禁止重复点击。

### InstrumentSelector

- 6 个宽基以 chip 形式多选；选中态 `primary-soft` + `primary` 文本。
- 每个 chip 可显示最新数据日期；过期时加 `status-warning` 点。
- 不可超过 6 个；清空时回退到默认 6 只。

### StatusBadge

- 变体：neutral / success / warning / danger / info。
- 高度 22px，全圆角，12px 字。
- 必须带文字；图标可选但推荐。
- 行情涨跌不使用此组件，使用 `market-up` / `market-down` 文本与箭头。

### MetricCard

- 结构：标签（`metric-label`）→ 数值（`metric-value`）→ 变化/分位（`caption`）→ sparkline（可选）。
- 数值颜色：普通数据用 `ink`；正负收益用 `market-up/down`；情绪分数用 `sentiment-fear/greed`。
- 右下角显示数据日期和来源徽标（`caption`，`ink-muted`）。
- 空值显示 `—`，不显示 0。

### DataTable

- 表头 `table-header`，行 `table-row`，选中 `table-row-selected`。
- 默认 36px 行高；数字列等宽右对齐；文本列截断加 tooltip。
- 排序箭头只在 hover/focus 时出现；排序状态常驻。
- 空状态、加载骨架、错误重试三种状态必须实现。
- 分页使用“每页 50/100/全部”，默认 50。

### KLineChart

- 蜡烛图：上涨 `market-up`，下跌 `market-down`，影线同色；平盘 `ink-muted`。
- 成交量柱：同色 30% 透明度；均线 MA5/20/60 用 `chart-1/2/3`。
- 十字光标、tooltip（`surface-elevated`，等宽数字）、区间切换 1M/3M/6M/1Y/3Y/ALL。
- 图表右上角显示复权口径与数据日期。
- 无数据时显示空状态，不显示空白坐标轴。

### ValuationChart

- PE/PB/ERP 折线用 `chart-1`，不借用红绿。
- 分位带：p20–p80 用 `primary-soft` 填充；p20/p80 虚线用 `border-strong`。
- 当前值用 `primary` 圆点 + 数值标签；历史极值用 `caption` 标注。
- 图例最多 4 项；超过时合并为“其他”。

### Gauge

- FGI 0–100：0–25 `sentiment-fear`，25–75 `ink-muted`，75–100 `sentiment-greed`。
- 指针与当前值文字必须同时存在；色盲用户可读。
- 不做彩虹色分段，不做 3D。

### FactorWeightEditor

- 每个因子一行：名称、说明、权重滑块、数字输入。
- 权重总和必须 100%；不等于 100 时显示 `status-danger` 内联错误，主按钮禁用。
- 提供“重置为默认”和“归一化”两个次级操作。
- 权重变更后显示“未保存”状态，离开页面前拦截。

### RuleBuilder

- 三态可视化：空仓 / 半仓 / 满仓；箭头表示允许的迁移。
- 每条迁移可配置阈值、确认天数、最短持有、冷却期。
- 阈值重叠或不可达时显示 `status-warning` 提示，不阻止保存但要求确认。
- 右侧实时预览最近 12 个月的信号点。

### BacktestPanel

- 顶部：策略版本、区间、成本假设、运行按钮。
- 运行中显示进度、已处理日期、可取消；失败显示错误摘要与重试。
- 结果：6 个指标卡（CAGR、Sharpe、MaxDD、Calmar、换手、暴露）+ 净值曲线 + 回撤面积 + 交易表。
- 基准曲线用 `chart-6`，策略用 `chart-1`，超额用 `chart-4`。

### SignalCard

- 结构：标的与日期 → 状态迁移（空仓→半仓）→ 分数 → Top 3 因子贡献 → 触发原因 → 数据截止日 → 操作。
- 状态迁移用文字 + 箭头；买入方向用 `market-up`，卖出方向用 `market-down`，但必须带“加仓/减仓/清仓”文字。
- 操作：确认、已执行、忽略；忽略必须填写原因。
- 过期信号降低不透明度到 60%，并标注“已过期”。

### JobManager

- 任务表：名称、频率、上次运行、下次运行、耗时、状态、操作。
- 状态：success / running / failed / paused；失败行左侧 2px `status-danger`。
- 日志抽屉：等宽字体、时间戳、级别颜色仅用于级别文字。
- 支持手动触发；运行中禁止重复触发。

### HoldingsTable

- 列：标的、持有份额、可用份额、成本价、市值、目标状态、建议动作。
- 目标与实际不一致时，建议动作列用 `status-warning` 文本，不使用红色按钮。
- 动作按钮为次级按钮，执行后写入日志。

### EmptyState / Loading / Error

- 空状态：一句说明 + 一个主操作；不要插画。
- 加载：骨架行/骨架卡片，不用全屏 spinner。
- 错误：内联 `status-danger` 文案 + 重试按钮；保留页面其他可用区域。

## Do's and Don'ts

### Do

- 用红绿只表达行情方向，并且同时给箭头和文字。
- 用蓝色表达操作与选中，用琥珀/蓝表达情绪。
- 用等宽数字、右对齐、固定小数位。
- 用 1px 边框和表面层级建立结构。
- 每个数据点显示 `as_of` 日期和来源徽标。
- 空值显示 `—`，并说明原因。
- 图表提供可访问的表格替代或数据下载。
- 动效只用于状态变化，120–180ms。

### Don't

- 不要用红色表示“错误/贪婪/上涨”三种含义。
- 不要用绿色表示“成功/恐惧/下跌”三种含义。
- 不要用渐变、发光、玻璃拟态、3D 图表。
- 不要在数据表里用居中文本。
- 不要用超过 6 种图表颜色。
- 不要用饼图展示超过 5 个分类。
- 不要把卡片套卡片。
- 不要用纯色块代替空状态或错误状态。
- 不要用动画掩盖加载失败。
- 不要在正文使用 12px 以下字号。

## Responsive Behavior

| 断点 | 行为 |
|---|---|
| ≥ 1440px | 完整侧栏 + 12 列网格 + 全部列 |
| 1280–1439px | 侧栏可折叠；图表高度降为 280px |
| 1024–1279px | 侧栏折叠为 64px；卡片从 4 列变 2 列 |
| 768–1023px | 单列；表格隐藏次要列，保留横向滚动 |
| < 768px | 只读模式：看状态、看信号；不做策略编辑与回测运行 |

移动端不是 MVP 目标；如果未来要做，单独设计，不把桌面表格硬塞进手机。

## Accessibility

- 正文对比度 ≥ 4.5:1；大文本 ≥ 3:1。
- 焦点：2px `focus-ring`，2px offset；键盘可达所有交互。
- 颜色不单独承载语义：涨跌配箭头，状态配图标/文字，情绪配区间文字。
- 表格使用 `<caption>`、`scope="col"`、`scope="row"`；排序状态用 `aria-sort`。
- 图表提供 `aria-label` 与“查看数据表”入口。
- 表单错误内联显示，使用 `aria-describedby` 关联；错误文案说明如何修复。
- 支持 `prefers-reduced-motion`：关闭过渡与图表动画。
- 模态框焦点锁定，Esc 关闭，关闭后焦点回到触发元素。

## Data Visualization

### 颜色规则

- 行情序列（K 线、收益）只能用 `market-up/down`。
- 非行情序列（PE、PB、ERP、基准、因子）只能用 `chart-1…6`。
- 因子贡献：正向贡献用 `sentiment-greed`，负向贡献用 `sentiment-fear`，并在 tooltip 中给出数值。
- 超过 6 条序列时，合并为“其他”或改用小倍数图，不增加颜色。

### 坐标与网格

- 轴线 `border`，网格线 `border` 20% 透明度。
- 轴标签 12px `ink-muted`；单位放在轴标题，不重复标注。
- Y 轴不从 0 开始时必须标注断轴；收益率曲线可以不断轴，但要标注。
- 不使用图表标题重复卡片标题；图例放在图表上方右侧。

### Tooltip

- 背景 `surface-elevated`，1px `border`，圆角 6px，阴影层级 2。
- 数字等宽；日期与数值左对齐；最多展示 6 行。
- 十字光标跟随，不遮挡当前点。

## Page Templates

### 1. 数据收集

```text
Page header: 数据收集 | 市场日期 | 数据新鲜度 | [立即同步]
Tabs: 标的配置 | 定时任务 | 数据质量
```

- **标的配置**：表格列 = 代码、名称、类型、关联 ETF、数据起点、最新日期、状态、操作。
- **定时任务**：表格列 = 任务、频率、上次运行、下次运行、耗时、状态、操作；操作含“立即运行”“查看日志”。
- **数据质量**：按严重度分组的 issue 列表；每条含标的、指标、日期、问题类型、处理状态。
- 空状态：“还没有配置标的” + 主操作“添加标的”。
- 错误：顶部内联告警，保留已加载数据。

### 2. 数据展示

```text
Page header: 数据展示 | 标的 chips | 日期范围 | 密度 | [导出]
Row 1: K 线（8 列，480px） | 指标卡 ×4（4 列）
Row 2: 估值图（8 列，320px） | 分位表（4 列）
Footer: 数据来源、as_of、新鲜度
```

- 指标卡：PE、PB、ERP、股息率；每张显示当前值、历史分位、`as_of`。
- K 线：红涨绿跌、成交量、MA5/20/60、区间切换。
- 估值图：折线 + p20–p80 分位带 + 当前点。
- 分位表：指标、当前值、1Y 分位、3Y 分位、10Y 分位、来源。
- 无数据：显示“该区间没有数据” + 调整日期按钮。

### 3. 策略配置

```text
Page header: 策略配置 | 版本徽标 | [保存新版本] [运行回测]
Left 7 列: 因子权重编辑器（6 个因子）
Right 5 列: 三态规则构建器 + 迁移列表
Bottom: 版本历史表 + 最近 12 个月信号预览
```

- 权重和必须 100%，否则主按钮禁用。
- 规则构建器显示允许的迁移；不可达状态用 `status-warning`。
- 未保存变更用顶部细条 `status-warning` 提示，离开拦截。
- 版本状态：draft / active / archived；归档版本只读。

### 4. 策略回测

```text
Page header: 策略回测 | 策略版本 | 区间 | [运行]
Row 1: 指标卡 ×6
Row 2: 净值曲线（8 列） | 回撤（4 列）
Row 3: 交易明细表（8 列） | 基准对比（4 列）
```

- 运行中：进度条 + 当前处理日期 + 取消。
- 结果：策略、基准、超额三条线；最大回撤点标注。
- 交易表：日期、动作、价格、份额、费用、状态前/后、原因。
- 失败：错误摘要 + 重试；保留上次成功结果。

### 5. 买卖信号

```text
Page header: 买卖信号 | 标的筛选 | 状态筛选 | 日期
List: SignalCard ×N
Empty: 今天没有新的状态切换（上次信号：2026-10-28）
```

- 卡片按日期倒序；新信号置顶并带 `primary` 左边条。
- 每张卡显示：标的、日期、状态迁移、分数、Top 3 因子贡献、原因、`data_as_of`。
- 操作：确认、已执行、忽略；忽略必须填写原因。
- 已执行信号不可撤销；纠错用新记录。
- 过期信号降低不透明度并标注。

### 6. 持仓与日志

```text
Page header: 持仓与日志 | [导入持仓] [新增交易]
Row 1: 持仓表（8 列） | 目标 vs 实际（4 列）
Row 2: 纪律日志（12 列）
```

- 持仓表：标的、份额、可用、成本、市值、目标状态、建议动作。
- 目标与实际不一致时，动作建议用 `status-warning` 文本，不用红色按钮。
- 日志：信号日期、信号状态、实际操作、偏离原因、备注。
- 执行率与偏离率做成两个小指标卡。

## Theme Mapping

亮色主题不是简单反色；行情红绿、情绪蓝琥珀需要单独校准。

| Token | 暗色 | 亮色 |
|---|---|---|
| `canvas` | `#0B0E14` | `#F6F7F9` |
| `surface` | `#11151D` | `#FFFFFF` |
| `surface-elevated` | `#161B24` | `#FFFFFF` |
| `surface-hover` | `#1B2230` | `#F1F4F8` |
| `ink` | `#E6EAF2` | `#101828` |
| `ink-muted` | `#8A94A6` | `#667085` |
| `ink-subtle` | `#5C6678` | `#98A2B3` |
| `border` | `#232A36` | `#E4E7EC` |
| `border-strong` | `#344052` | `#D0D5DD` |
| `primary` | `#5B8CFF` | `#2F6BFF` |
| `on-primary` | `#0B0E14` | `#FFFFFF` |
| `primary-hover` | `#7AA2FF` | `#1F5AE0` |
| `primary-soft` | `#1A2740` | `#EAF1FF` |
| `market-up` | `#F04438` | `#D92D20` |
| `market-down` | `#12B76A` | `#079455` |
| `sentiment-fear` | `#38BDF8` | `#0284C7` |
| `sentiment-greed` | `#F59E0B` | `#B54708` |
| `status-success` | `#22C55E` | `#067647` |
| `status-warning` | `#F59E0B` | `#B54708` |
| `status-danger` | `#F04438` | `#B42318` |
| `status-info` | `#38BDF8` | `#175CD3` |
| `chart-1` | `#5B8CFF` | `#2F6BFF` |
| `chart-2` | `#A78BFA` | `#7A5AF8` |
| `chart-3` | `#22D3EE` | `#06AED4` |
| `chart-4` | `#F59E0B` | `#DC6803` |
| `chart-5` | `#F472B6` | `#DB2777` |
| `chart-6` | `#94A3B8` | `#667085` |
| `focus-ring` | `#8AB4FF` | `#2F6BFF` |

```css
:root,
[data-theme="dark"] {
  --color-canvas: #0B0E14;
  --color-surface: #11151D;
  --color-ink: #E6EAF2;
  --color-primary: #5B8CFF;
  /* 其余 token 同上 */
}

[data-theme="light"] {
  --color-canvas: #F6F7F9;
  --color-surface: #FFFFFF;
  --color-ink: #101828;
  --color-primary: #2F6BFF;
  /* 其余 token 同上 */
}
```

## Implementation Alignment

### Tailwind

```ts
colors: {
  canvas: "var(--color-canvas)",
  surface: "var(--color-surface)",
  "surface-elevated": "var(--color-surface-elevated)",
  ink: "var(--color-ink)",
  "ink-muted": "var(--color-ink-muted)",
  border: "var(--color-border)",
  primary: "var(--color-primary)",
  "on-primary": "var(--color-on-primary)",
  "market-up": "var(--color-market-up)",
  "market-down": "var(--color-market-down)",
  "sentiment-fear": "var(--color-sentiment-fear)",
  "sentiment-greed": "var(--color-sentiment-greed)",
  // ...
}
```

- 组件中禁止出现硬编码 hex；所有颜色引用 token。
- 圆角、间距、字号同样通过 Tailwind theme 扩展，不写任意值。
- shadcn/ui 的 `--background`、`--foreground`、`--border`、`--ring` 映射到本文件 token。
- ECharts 主题单独维护：背景透明，轴线 `border`，文字 `ink-muted`，tooltip `surface-elevated`。

### 字体

- Inter 与 JetBrains Mono 使用本地打包或系统回退，不依赖运行时外网。
- 中文回退到 PingFang SC / 思源黑体 / 微软雅黑。
- 数字启用 `font-variant-numeric: tabular-nums`。

### 动效

```text
fast: 120ms
base: 180ms
easing: cubic-bezier(0.2, 0.8, 0.2, 1)
```

- 只用于 hover、展开、状态切换；图表默认不做入场动画。
- `prefers-reduced-motion` 下全部关闭。

### 数据契约

- 每个指标必须显示 `as_of` 和数据来源徽标。
- `stale` / `missing` / `conflict` 状态必须可见，不能静默隐藏。
- 信号卡必须显示 `data_as_of`，确保复盘时知道当时看到的数据。

## Known Gaps

- **needs-design-verification**：`market-up` / `market-down` 在 `surface` 与软背景上的对比度需用工具实测，特别是 13px 表格数字。
- **needs-design-verification**：亮色主题的 K 线红绿、分位带和图表序列需要在真实数据上校准，不能只靠 token 表。
- **needs-design-decision**：移动端只做只读是否足够；如果要在手机上下单或改策略，需要单独设计交互。
- **needs-design-decision**：图表库最终选 ECharts 还是 lightweight-charts；本契约默认按 ECharts 的 theme 能力编写。
- **needs-design-decision**：默认密度用 compact 还是 comfort；本契约默认 compact，并提供切换。

## 投研简报风格融合（2026-11-06）

用户指定参考“全球聪明钱持仓雷达”的可见设计语言，融合到现有研究终端。
保留默认暗色、侧栏、等宽数据、细边框、语义色和可追溯信息。

- 亮色主题：暖纸底 `#F3F0E9`、纸面 `#FAF8F3`、墨色 `#262521`、
  次要文字 `#6C6860`、细线 `#DCD7CD`、朱红操作色 `#B63D28`。
- 暗色主题：保留原深色表面，操作强调改珊瑚色 `#FF8A72`，图表序列色独立。
- 页面和分组标题使用宋体栈，正文保持无衬线，价格、日期与分数保持等宽。
- 页面标题区增加细分隔线；分组标题用短朱红线标记层级，筛选按钮采用紧凑圆角。
- 行业恐贪八类概览改为连续指标条，桌面四列、移动两列；分隔线组织信息，
  选中项用浅操作色背景与情绪色底线标识，仍保留源情绪标签文字。

本节覆盖上文原蓝色操作色与纯白亮色的历史示例；主题实际值以
`web/src/styles/tokens.css` 为准。参考内容和持仓功能不属于本系统需求。
