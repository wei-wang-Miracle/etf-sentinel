# 工程初始化实施清单

目标：仅初始化工程结构，不实现业务功能。
架构：React + TypeScript + Vite，FastAPI，PostgreSQL，Compose 三服务。

- [x] 初始化 Git 开发分支及忽略规则。
- [x] 创建前端入口、空模块目录和契约中的主题变量。
- [x] 创建后端入口与进程健康检查，声明数据库开发依赖。
- [x] 配置容器构建、服务依赖、数据库持久化与 Web 代理。
- [x] 保存设计契约并编写启动及验证命令。
- [x] 验证前端构建、TypeScript 检查、Ruff、API 健康检查和 Compose 配置。

验证范围：未构建容器镜像或启动 Compose 服务。
