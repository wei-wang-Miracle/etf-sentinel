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
- `runs.job_id` 关联 `jobs.job_id`，1 为 ETF、2 为行业恐贪、3 为国家队持仓；旧运行回填为 1。
  三任务的配置、定时水位、运行记录与互斥锁独立。

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
