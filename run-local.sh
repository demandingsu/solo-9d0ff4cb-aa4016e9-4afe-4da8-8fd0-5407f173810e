#!/usr/bin/env bash
# 不使用 Docker 时的离线启动方式：
#   1) 后台启动本地示例站（标准库 http.server，端口 8080）
#   2) 启动供应商归一核对页（端口 8000）
# 打开 http://127.0.0.1:8000/ ，输入 http://127.0.0.1:8080/list/index.html
set -euo pipefail
cd "$(dirname "$0")"

python3 -m http.server 8080 --directory example-site/html &
SITE_PID=$!
trap 'kill $SITE_PID 2>/dev/null || true' EXIT

echo "示例站: http://127.0.0.1:8080/list/index.html"
exec env PYTHONPATH="$(pwd)" python3 -m app
