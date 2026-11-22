#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ] || [ ! -d node_modules ] || [ ! -f dist/index.html ]; then
  echo "首次运行或依赖变更，先安装并构建…"
  uv sync --python 3.12
  npm ci
  npm run build
fi
.venv/bin/python ops/local_runtime.py start
PORT="$(.venv/bin/python -c 'import sys; sys.path.insert(0, "ops"); from local_runtime import read_env; print(read_env()["HKUS_PORT"])')"
open "http://127.0.0.1:${PORT}" || true
echo "服务在本机后台运行。停止时双击「停止港美股工作台.command」。"
read -r "?按回车关闭..."
