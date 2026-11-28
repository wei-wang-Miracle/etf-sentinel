# 数据库建设与字段语义

数据库遵循同义同名、见名知意、详尽注释三项原则。
所有业务表与字段说明同时保存在 SQLAlchemy 元数据和 PostgreSQL COMMENT 中。
API 为兼容已有前端保留短字段名，通过 ORM 显式映射到语义完整的物理列。

## 命名约定

以下字段语义在不同表间保持一致。不同含义的开关分别命名，避免误用。

| 语义 | 物理字段 |
| --- | --- |
| ETF证券代码 | `instrument_code` |
| ETF名称 | `instrument_name` |
| 源交易日期 | `trade_date` |
| 采集区间起止 | `collection_start_date`、`collection_end_date` |
| 日行情价格 | `open_price`、`high_price`、`low_price`、`close_price` |
| 成交量额 | `trading_volume`、`trading_amount` |
| 涨跌百分数 | `price_change_pct` |
| 源复权收盘值 | `adjusted_close_price` |
| 启用采集 / 启用定时 | `collection_enabled` / `schedule_enabled` |
| 每日调度时刻 | `scheduled_time` |
| 任务编号 / 运行编号 | `job_id` / `run_id` |
| 运行状态 / 触发方式 / 区间日志 | `run_status` / `trigger_type` / `collection_logs` |

源更新时间保留原始文本与未知时区说明；本地采集及运行时间使用带时区时间戳。
成交量额单位未经确认时，注释明确写为源单位待确认，不擅自推断。
JSON 日志保留现有键以兼容 API，其内部结构记录在该字段注释中。

## 迁移与检查

`0002_schema_semantics` 原地重命名字段并添加表和字段注释，不重建或删除行情数据。
数据库中的主外键列同步重命名，ORM 与冲突更新语句同步调整。

```bash
cd api
alembic upgrade head
alembic check
```

连接参数必须指向本地项目库。独立测试库中的回归测试会检查数据库名称、
表注释、字段注释与模型一致，外键字段与被引用主键使用相同语义名。
现有生产环境严格只读约束不因本地修库授权改变。

## 行业恐贪数据表

迁移 `0003` 新增以下表，保留既有 ETF 数据，所有字段均带数据库注释。

- `sentiment_categories`：`category_key` 唯一标识、`category_name` 源名称、
  `index_name` 关联指数、`collection_enabled` 采集开关、`snapshot_date` /
  `snapshot_score` / `snapshot_label` 源快照、`collected_at` 目录采集时间。
- `sentiment_daily`：`category_key` 与 `trade_date` 联合主键，
  `fear_greed_score` 为 0—100 分数，`close_price` 为指数收盘点位（可空），
  `collected_at` 为该条最近采集时间。零分有效，不将缺失补零。
- `runs.job_id` 关联 `jobs.job_id`，1 为 ETF、2 为行业恐贪、3 为国家队持仓、4 为指数估值、5 为观察策略日计划；旧运行回填为 1。
  五任务的配置、定时水位、运行记录与互斥锁独立。

日数据的 `trade_date`、`close_price`、`collected_at` 与已有同义字段统一命名；
具体单位由表字段注释明确，ETF 价格与指数点位不可直接比较。

## 国家队持仓数据表

迁移 `0004` 新增两表及任务3，保留行情和恐贪数据，字段均带中文注释。

- `national_team_instruments`：`instrument_code` 主键，`instrument_name`、
  `index_name` 为源名称；`estimation_start_date` 固定2026-01-01；
  `reference_holding_pct` 是上游披露未核实的参考百分数，可空；
  `source_url` 为来源，`source_available` 为最近目录可用状态，
  `last_success_at` 为带时区成功核验时间。
- `national_team_daily`：`instrument_code` / `trade_date` 联合主键；
  `estimated_holding_pct` 为0至100百分数，源比例缺失或份额为零时为空；
  `collected_at` 为带时区首次入库或比例修订时间，未变不重写。

不保存外站价格或总份额；同代码日K读取已有 `candles`。

## 统一行情标的迁移

迁移 `0005` 将国家队18只ETF插入统一 `instruments`，冲突时不修改已有配置。
与原五只去重为20只。新增默认启用，历史起点2020-01-01，名称先来自国家队
目录，后由行情源返回更新；同步更新代码与名称字段COMMENT。
降级保留新增配置与行情，避免删除已经采集的数据。

## 策略回测数据表

迁移 `0006` 新增两表，全部字段有中文COMMENT，保留此前行情及采集记录。
详细输入、账户和复算口径见[策略与回测](backtesting.md)。

- `backtest_sources`：`instrument_code`主键并关联统一标的；`source_url`、
  `checked_through_date`（北京时间读取日，非完整性保证）、`collected_at`、
  `source_sha256`、`source_html`保留来源证据；`corporate_actions`存分红登记日、
  除息日、发放日、每份人民币元金额字符串及历史折算日期/比例。
- `backtest_runs`：`backtest_run_id`自增主键，`instrument_code`关联统一标的，
  `strategy_key`、`created_at`、`input_sha256`用于定位实验；`input_snapshot`
  包含参数、预热行情、权益、原始来源、日历和版本；`result_snapshot`存策略/
  基准逐日账户、决策、模拟成交、分红账本与绩效。金额保存十进制字符串。

权益更新按代码覆盖最新来源，但原实验保留完整来源快照，不随行情或权益修订
更新。实验只插入和读取，无覆盖接口；版本变化时复算明确拒绝不兼容实验。

## 指数估值数据表

迁移`0007`创建七张独立表，登记8指数、20关联和任务4，并更新任务编号注释。
所有表和字段均带中文COMMENT，不变更ETF行情或回测数据。

- `research_indices`：`index_code`完整源代码主键，`index_name`中文名、
  `chatbi_code`六位行情查询代码、`collection_enabled`启停。
- `instrument_index_links`：`instrument_code/index_code`联合主键和外键，
  `mapping_evidence/verified_date`记录关联依据及本地核验日期。
- `index_valuation_daily`：`index_code/metric_key/trade_date`联合主键，
  `metric_value`十进制原值、`value_status`有效状态、`collected_at`新增或修订时间。
  值单位：PE/PB倍，股息率/ROE百分数，风险溢价差值百分点；缺失可空，无效原值保留。
- `index_valuation_revisions`：`revision_id`自增主键，指数/指标/源日期、
  `old_value/new_value`、`old_status/new_status`、`observed_at/run_id`。
  首次观察旧值和旧状态为空；与日估值同事务提交。
- `index_valuation_snapshots`：`snapshot_id`自增主键，`index_code`、
  `content_sha256/source_payload/observed_at/run_id`保存源概览、详情、
  各指标整段统计及覆盖摘要，按相邻内容去重；观测时刻不是源发布时间。
- `index_candles`：`index_code/trade_date`联合主键，`open_price/high_price/`
  `low_price/close_price`均为指数点位，`trading_volume/trading_amount`保留源单位，
  `price_change_pct`百分数、`source_updated_at`源文本及`collected_at`本地时刻。
- `index_collection_windows`：`index_code/collection_start_date`联合主键，
  `collection_end_date`成功窗口截止；失败撤销水位以便恢复，空响应不代表完整。

本地回看分位读取完整历史计算后再过滤显示日期，不存成来源历史分位。
采集和统计边界见[指数估值说明](index-valuations.md)。

迁移 `0009` 将权益源中文注释调整为配置内 ETF 动态资格，未改变字段类型或删除数据；三期功能复用现有表，详见[投研工作台说明](research-workbench.md)。

## 完整持仓同步集合

迁移0011补充账户完整持仓集合证据，不依赖策略分配。
- `account_sync_runs.holdings_snapshot`：完整集合代码、源日期及采集时间；空数组与未取得完整集合的NULL不同。

集合头和明细通过单条SQL在同一快照读取；同日消失仓位不继续作为当前持仓，
解析失败不覆盖上次完整集合。旧记录缺少集合证据时保留兼容回退，重新完整同步后采用新证据。
所有业务表及字段的名称、类型、约束和中文注释由独立测试库检查。

## FundDB ETF 档案与份额流数据表

迁移 `0022` 新增任务7及两张只面向配置内 ETF 的观察表；不把 FundDB 全市场目录写入
`instruments`，不回填首次成功采集前的日度截面，也不将该数据接入当前策略因子。

- `etf_catalog_profiles`：以 `instrument_code` 为主键并关联 `instruments`，保存基金全称、分类、源披露跟踪指数、详情页相关度、成立日、管理/托管费、联接基金代码、来源接口和最近核验时间。`tracking_index_code` 与 `index_corr` 只作辅助核验；不会自动生成 `instrument_index_links`。
- `etf_flow_daily`：以 `instrument_code` / `trade_date` 联合主键，保存规模（亿元）、份额（亿份）、7/30日份额净变动（亿份）、折溢价率、申购/赎回状态与最近采集时间。正负份额变动按源值保留，缺失不补零；仅关键字段修订时更新 `collected_at`。
- `jobs.job_id=7`：ETF 档案与份额流任务，默认北京时间 `01:25`；与任务1—6使用独立运行记录和数据库建议锁。

## 因子、策略关系与比较

迁移0018破坏性重建策略域，所有业务表和字段带中文注释。不保存可执行算法、历史因子或可选策略版本。

- `research_factors`：因子身份、名称、分类、输出含义及是否可以显示在行情图。
- `research_strategy_factors`：代码定义的策略身份和可观测因子关系，登记角色、展示顺序。
- `research_strategy_scopes`：迁移 `0026` 新增，结合 `instruments.research_category` 登记代码策略的研究作用域（`universal` 通用或 `category` 分类绑定）、研究版本号、证据等级（`baseline`、`cross_unit_verified`、`single_unit_candidate`、`holdout_watch`、`rejected`）、采用准入布尔值 `adoptable` 与实证摘要 `evidence_summary`，确保界面仅展示「通用 + 当前 ETF 所属分类绑定策略」并只开放通过研究门禁的分类策略进入盘前信号。
- `strategy_comparisons` 与 `strategy_comparison_factors`：单次比较的输入、结果、摘要以及成功轨道的因子关系。
- `instrument_strategy_assignments`：每只 ETF 至多一条当前策略分配，包含当前策略、采用依据和状态。
- `strategy_signals`：每条分配和执行日唯一，保存该日计划、策略名称和证据、跳过原因。
- `strategy_execution_links`：人工关联的累计委托，以账户、源日期、委托号定位，保存确认份额和依据。

迁移删除旧版本、观察批次、比较、计划和执行关联，并删除旧比较引用的模拟轨道及旧算法回测。未被旧比较引用的通用回测和真实账户数据保留，迁移不可逆。盘前生成须遵守一致性读和交易时点限制，见[策略与因子](single-etf-strategies.md)。
