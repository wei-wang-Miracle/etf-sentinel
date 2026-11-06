# ETF Sentinel

ETF Sentinel 是一个自用的 ETF 投研与买卖信号产生平台，初期关注宽基 ETF
择时研究，以及每日或信号驱动的买卖提示，辅助个人投资决策。

项目按实际使用需求逐步演进。已实现 20 只 ETF 的统一标的配置、历史日行情采集入库
和日 K 展示。开发协作约定见 [AGENTS.md](AGENTS.md)。

## 当前状态

当前可使用七个页面，操作与口径详见 [历史日行情说明](docs/daily-data.md)。

- 标的配置：原五只与国家队十八只去重，共 20 只，支持采集启停与历史起点设置。
- 定时任务：默认北京时间每日 01:00，支持手动运行、暂停、区间日志和失败重试。
- 行情展示：读取本地日 K 与成交量，支持 MA5/10/20/30/60、切换标的、日期范围、缩放及暗亮主题。
- 行业恐贪：八类情绪着色概览、恐贪与指数双轴合图、紧凑概览与日期筛选；首次五年、后续增量采集。
- 国家队持仓：18 只 ETF 估算比例入库、增量写入，与统一采集的本地日 K 同图双轴对照。
- 指数估值：20只ETF关联8指数，五类日频估值、独立指数日K、来源分位与本地回看分位，图表对照；任务4每日01:30。
- 策略回测：510500与512100的均线规则、统一成交核算、净值/回撤/仓位、执行日买卖标记、实验入库与快照复算。
- 分析页：紧凑筛选、主要指标与图表优先，图表带代码/周期/复权口径/区间/来源图注和“仅供研究”提示；悬停查看数据；不再展示底部明细表。
- 数据库：PostgreSQL，Alembic 迁移，行情幂等更新并保留源更新时间和采集时间。
- 工程：React + TypeScript + Vite + ECharts、FastAPI、Docker Compose 三服务配置。

ETF 数据源仅提供历史日数据，采集截至昨日；不提供实时行情。
本地行情未声明复权口径，图上均线按源收盘计算并在图注标注“复权口径未确认”，
不把它当作前复权数据。
行业恐贪保留源日期，独立任务默认每日 01:10，无需 ChatBI 凭据；
详见[行业恐贪说明](docs/industry-sentiment.md)。
国家队持仓独立任务默认每日 01:20，无需 ChatBI 凭据；
固定基准完整核验、仅新增和修订写入，详见[国家队持仓说明](docs/national-team.md)。
指数估值完整历史核验、增量写入及修订证据，详见[指数估值说明](docs/index-valuations.md)。
已实现均线规则与历史回测，详见[策略与回测说明](docs/backtesting.md)。
国家队/恐贪组合策略、实时买卖提示尚未实现。实际历史范围取决于源接口，
不保证覆盖到配置起点；回测遇缺日或权益校验失败会拒绝计算。

## 已确定方向与待讨论事项

当前确定的方向是个人使用、ETF 投研和买卖信号产生。具体功能以逐次确认的
需求为准，不预先固定完整功能清单。

后续可以围绕以下问题讨论，列出不代表已排期或承诺实现：

- 研究范围：是否扩展标的、关联指数、观察指标或其他数据来源？
- 策略研究：如何定义择时规则、验证方法、成本和风险约束？
- 信号提示：何时计算、如何解释触发原因、通过什么渠道提醒？
- 使用与复盘：是否需要记录持仓、实际操作及信号执行情况？

买卖提示与自动下单分开讨论，当前未规划自动交易。

## 功能组织与协作方式

你只需要提出功能点，开发代理负责根据平台定位完成模块归属、功能设计、
实现与验证，并持续维护系统结构和文档。常规模块划分与技术选择由代理处理，
关键业务歧义或目标冲突再与你澄清。

[功能地图](docs/feature-map.md)统一记录业务域边界、功能归属和落地状态。
每次功能变化同步更新地图与本文，避免功能不断叠加后失去整体结构。
业务域用于组织需求，不表示相关功能已实现或已排期。

## 设计方向

界面遵循 [Ledger Terminal 设计契约](docs/design-contract.md)：中文优先、
暗色优先、数据密集、低装饰，行情、情绪和系统状态分别表达。
融合用户指定参考页的暖纸亮色、宋体标题、朱红操作强调及连续指标条；
暗色保留终端感，行情、情绪和系统状态保持独立颜色语义。
契约中的页面和组件是设计参考，不代表当前功能范围或开发承诺。

## 目录

项目将前后端独立组织，使用 Compose 编排三个服务。

```text
api/                  FastAPI、采集服务、调度与测试
  app/                应用入口
  migrations/         Alembic 数据库迁移
  tests/              单元及独立数据库集成测试
web/                  React + TypeScript + Vite
  src/components/     共享组件
  src/pages/          页面模块
  src/lib/            前端工具
  src/styles/         设计变量及基础样式
docs/                 功能地图、设计契约和功能说明
compose.yaml          postgres + api + web
```

## 本地一键启动（推荐）

安装 Docker、Python 3.12+、Node.js 22 后，在项目根目录运行：

```bash
./scripts/start-local.sh
```

脚本只用 Docker 启动 PostgreSQL，前后端运行在本机；自动准备 Python 虚拟环境、
安装依赖、运行迁移，然后启动前后端。前端默认 http://localhost:5173，
API 默认 http://localhost:8000/docs。按 Ctrl+C 停止本次启动的前后端，数据库保留。

在另一终端重启本地前后端：

```bash
./scripts/start-local.sh restart
```

无参数等同 `start`，保持前台运行。`restart` 等待旧启动器清理前后端后，
重新准备依赖、执行迁移并启动服务；未运行时直接启动，PostgreSQL 和数据保留。
重启后的服务由执行 `restart` 的终端管理，按 Ctrl+C 可停止。
同一项目禁止重复启动；进程状态保存在被 Git 忽略的 `.local/start-local.lock`，
使用系统文件锁和进程身份校验；身份查询固定语言及时区，支持不同终端环境重启。
遇到未知进程占用端口时拒绝启动，不按端口杀进程。
从不具备进程登记的旧版脚本升级时，先在原终端按一次 Ctrl+C，再使用新版启动。


首次自动创建 `.env`，填写行情源凭据后重新启动即可采集。
默认数据库宿主端口为 `55432`，可通过 `.env` 的 `PGPORT` 修改；
API 和 Web 端口分别由 `API_PORT`、`WEB_PORT` 设置，代理同步调整。
数据库用户、口令和库名沿用 `POSTGRES_*` 配置。
如果本机指定数据库端口已有服务，脚本复用该连接并校验，不重启既有容器。
前后端端口被占用时明确退出，不杀既有进程、不自动切换到其他端口。
新建的 Compose 数据保存在命名卷 `postgres_data`；现有开发库可继续使用。

## Docker 三服务启动（可选）

需要 Docker Engine 和 Compose 插件。在项目根目录执行：

```bash
cp .env.example .env
# 编辑 .env，填写 CHATBI_ACCESS_CODE 和 CHATBI_TOKEN
docker compose up --build -d
```

在 `.env` 填写 `CHATBI_ACCESS_CODE` 和 `CHATBI_TOKEN` 后启动采集。
凭据只保留在后端环境中，示例文件不含真实值。
容器 API 启动时自动迁移数据库；首次启动可能补触发当天到期的采集任务。

访问[前端](http://localhost:5173)和 [API 文档](http://localhost:8000/docs)。
通过 [Web 代理健康检查](http://localhost:5173/api/health)验证代理，或访问
[API 健康检查](http://localhost:8000/health)验证 API 进程。
健康检查只表示 API 存活，不检查数据库连接。
PostgreSQL 仅在 Compose 内网提供服务，数据保存到命名卷。
本地示例口令仅供开发使用。数据库连接参数通过 PGHOST、PGPORT、PGDATABASE、
PGUSER、PGPASSWORD 注入；迁移自动创建业务表及 20 只标的配置。

## 本地开发

前端需要 Node.js 22，后端需要 Python 3.12 或更新版本。
先准备可访问的本地 PostgreSQL，在根目录 `.env` 填写数据源及数据库连接参数。
后端启动前载入该文件，再分别在两个终端执行：

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
set -a
source ../.env
set +a
alembic upgrade head
uvicorn app.main:app --reload --env-file ../.env
```

```bash
cd web
npm ci
npm run dev
```

Vite 将 `/api` 代理到本地 API；容器内由 Nginx 提供相同代理。
数据库连接使用 `PGHOST`、`PGPORT` 等变量，详细说明见
[历史日行情说明](docs/daily-data.md)。

## 验证

按改动执行构建、静态检查与业务测试。集成测试只允许独立的
`etf_sentinel_test` 数据库，并会清空该测试库中的业务表，禁止指定真实数据存储库。

```bash
cd web
npm run build
npm run typecheck
```

在安装后端开发依赖后，于 `api/` 执行：

```bash
ruff check app tests migrations
pytest -q
```

默认跳过数据库集成测试。准备独立测试库后，设置 `PGDATABASE=etf_sentinel_test`
及对应连接变量，执行 `alembic upgrade head` 和 `pytest -q`。
在项目根目录执行 `docker compose --env-file .env.example config --quiet`
检查编排配置。停止服务使用 `docker compose down`，命名卷会保留。

## 数据库建设

相同语义使用相同字段名，字段见名知意，所有业务表和字段必须有详细中文数据库注释。
完整约定见 [AGENTS.md](AGENTS.md)；当前数据字典见
[数据库说明](docs/database.md)。修改通过 Alembic 迁移执行，保留已有数据。

## 文档如何维护

每次新增、调整或移除功能，都在同一次变更中同步更新本文档。

- 当前状态只记录已实现能力，未完成或尚未验证的部分明确说明。
- 已确认的后续需求可以单独记录，探索想法保留在待讨论事项中。
- 功能新增或归属调整时，同步更新[功能地图](docs/feature-map.md)中的状态、
  依赖及设计或实现入口。
- 启动方式、依赖、环境变量、目录或验证命令变化时，同步修订对应章节。
- 长期协作规则变化时更新 [AGENTS.md](AGENTS.md)；详细方案放入 `docs/`
  并从本文链接，不在 README 中累积完整开发过程。
