#!/usr/bin/env bash
set -euo pipefail

# 哔哩轻小说 Studio Pro - Linux 服务器 Web 启动脚本
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    else
        echo "[错误] 未检测到 python3，请先安装 Python 3.10+" >&2
        exit 1
    fi
fi

HOST="${BILINOVEL_HOST:-0.0.0.0}"
PORT="${BILINOVEL_PORT:-8765}"

echo "[*] 使用解释器: $PYTHON_BIN"
echo "[*] 启动 Web 服务: http://${HOST}:${PORT}/"
exec "$PYTHON_BIN" launch_gui.py --web --no-browser --host "$HOST" --port "$PORT" "$@"
