#!/bin/zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ -x .venv/bin/python ]; then
  .venv/bin/python ops/local_runtime.py stop
else
  python3 ops/local_runtime.py stop
fi
read -r "?按回车关闭..."
