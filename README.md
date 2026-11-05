# ETF Sentinel

宽基 ETF 择时研究平台的工程骨架。当前不含行情采集、策略、回测或买卖提示功能。
设计遵循 [Ledger Terminal 设计契约](docs/design-contract.md)。

## 目录

项目将前后端独立组织，使用 Compose 编排三个服务。

```text
api/                  FastAPI、数据库依赖及测试目录
  app/                应用入口
  tests/              后端测试
web/                  React + TypeScript + Vite
  src/components/     共享组件
  src/pages/          页面模块
  src/lib/            前端工具
  src/styles/         设计变量及基础样式
docs/                 设计契约及初始化清单
compose.yaml          postgres + api + web
```

## Docker 启动

需要 Docker Engine 和 Compose 插件。在项目根目录执行：

```bash
cp .env.example .env
docker compose up --build -d
```

访问前端 http://localhost:5173 ，API 文档 http://localhost:8000/docs 。
通过 http://localhost:5173/api/health 验证 Web 代理，或访问
http://localhost:8000/health 验证 API 进程。
健康检查只表示 API 存活，不检查数据库连接。
PostgreSQL 仅在 Compose 内网提供服务，数据保存到命名卷。
本地示例口令仅供开发使用。数据库连接参数通过 PGHOST、PGPORT、PGDATABASE、
PGUSER、PGPASSWORD 注入；当前未创建业务表或迁移。

## 本地开发

前端需要 Node.js 22，后端需要 Python 3.12 或更新版本。
分别在两个终端执行：

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

```bash
cd web
npm ci
npm run dev
```

Vite 将 `/api` 代理到本地 API；容器内由 Nginx 提供相同代理。
SQLAlchemy、psycopg 和 Alembic 已声明依赖，尚未配置业务模型和迁移。
暗色变量默认生效，亮色变量通过根元素 `data-theme="light"` 使用；尚无切换交互。

## 验证

初始化阶段使用构建、静态检查和健康检查验证，不包含业务测试。

```bash
cd web
npm run build
npm run typecheck
```

在安装后端开发依赖后执行 `ruff check app`。
在项目根目录执行 `docker compose --env-file .env.example config --quiet`
检查编排配置。停止服务使用 `docker compose down`，命名卷会保留。
