#!/usr/bin/env bash
# 在前台管理本地前后端，数据库由 Docker 持久化运行。
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
case "${1:-start}" in
  start|restart) ;;
  -h|--help) echo "用法：./scripts/start-local.sh [start|restart]（默认 start，前台运行；数据库保留）"; exit 0 ;;
  *) echo "未知命令；用法：./scripts/start-local.sh [start|restart]" >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then echo "仅接受一个命令：start 或 restart" >&2; exit 2; fi
for tool in docker python3 npm; do
  command -v "$tool" >/dev/null || { echo "缺少依赖：$tool" >&2; exit 1; }
done
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "已创建 .env；可配置行情源凭据后重新启动以启用采集。"
fi
if [[ ! -x api/.venv/bin/python ]]; then python3 -m venv api/.venv; fi
api/.venv/bin/python -m pip install -e 'api[dev]'
if [[ ! -d web/node_modules ]]; then (cd web && npm ci); fi
exec api/.venv/bin/python "$PROJECT_ROOT/scripts/start_local.py" "$@"
