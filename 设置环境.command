#!/bin/zsh
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv。请先按 https://docs.astral.sh/uv/getting-started/installation/ 安装 uv，再重新运行此文件。"
  read -r "?按回车关闭..."
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "未找到 Node.js / npm。请安装受 Vite 支持的 Node.js 版本（20.19+ 或 22.12+），然后重新运行。"
  read -r "?按回车关闭..."
  exit 1
fi

echo "安装本机 Python 依赖…"
uv sync --python 3.12
echo "安装前端锁定依赖…"
npm ci
echo "构建中文工作台…"
npm run build
echo "环境就绪。双击「启动港美股工作台.command」即可打开。"
read -r "?按回车关闭..."
