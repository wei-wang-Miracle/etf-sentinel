# 国家队持仓对照实施计划

用户已确认开始实施，以源接口十八只基金为持仓采集范围。

**目标：** 持仓估算比例入库、增量更新，并与已有本地日 K 对照。

**架构：** 保留固定 2026-01-01 估算基准，完整请求同基准序列，只写新增或
修订记录；不采集源价格。复用任务配置、数据库锁、运行日志和 ECharts。

**技术栈：** FastAPI、SQLAlchemy、PostgreSQL、Alembic、React、TypeScript。

## 执行步骤

- [x] 先写 `api/tests/test_national_team.py`：测试源状态、固定区间、
  重复代码、非法比例、空序列和日期校验；执行 pytest 确认新模块缺失。
- [x] 在 `api/app/models.py` 增加目录和比例日表，在
  `api/migrations/versions/0004_national_team.py` 创建带中文注释的表及任务3。
- [x] 新建 `api/app/national_team.py`，逐基金原子入库、只更新变化数据，
  源缺失或倒退保留历史并失败；新增独立调度与恢复。
- [x] 新建 `api/tests/test_national_team_database.py`：验证重复采集不重写、
  全历史修订、失败隔离、目录缺失、只读本地查询及任务3独立锁。
- [x] 新建 `api/app/national_team_routes.py`，实现本地目录、日期历史、
  同代码日K查询及任务接口；挂载至 `api/app/main.py`。
- [x] 新建 `web/src/pages/NationalTeam.tsx`，扩展 `KLine.tsx` 支持比例对照，
  在 `App.tsx` 增加导航、`Jobs.tsx` 增加任务3；不扩写现有五只行情配置。
- [x] 本地执行迁移、首采及重复采集，验证十八只覆盖、写入计数和日期；
  独立测试库执行 pytest，前端执行 build/typecheck，后端执行 ruff，
  根目录执行 Compose config 与 diff --check。
- [x] 更新 README、功能地图、数据库说明、使用说明和已确认设计，
  交付实际验证结果与无本地K线标的的限制。

## 关键验收

页面切换日期不重新锚定比例；源价格不入库；同日比例零值与缺失分开。
新增基金只进入独立国家队目录，现有五只行情任务与行业恐贪任务保留。
未变化日记录的采集时间保持不变，最后成功核验时间独立展示。
