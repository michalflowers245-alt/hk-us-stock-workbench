#!/bin/zsh
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ -x .venv/bin/python ]; then
  .venv/bin/python ops/macos_autostart.py stop
else
  python3 ops/macos_autostart.py stop
fi
read -r "?按回车关闭..."
