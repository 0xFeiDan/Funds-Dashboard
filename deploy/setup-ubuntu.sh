#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null || { echo "缺少 python3"; exit 1; }
command -v npm >/dev/null || { echo "缺少 Node.js/npm"; exit 1; }
command -v pm2 >/dev/null || { echo "缺少 PM2。先执行：sudo npm install -g pm2"; exit 1; }

python3 -m venv "$ROOT/backend/.venv"
"$ROOT/backend/.venv/bin/pip" install --upgrade pip
"$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
(cd "$ROOT/frontend" && npm ci && npm run build)

cd "$ROOT"
pm2 startOrReload ecosystem.config.cjs --update-env
pm2 save
echo
echo "已启动：http://Ubuntu服务器IP:8089"
echo "首次登录账号和密码：cat $ROOT/backend/data/first-login.txt"
