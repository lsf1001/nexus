#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.nexus/pyinstaller"

"$ROOT_DIR/.venv/bin/python" -m pip install pyinstaller
# 用 onedir 模式（不是 onefile），避免启动时解压临时目录 3-5s 等待。
# 产物: dist/nexus-backend/nexus-backend (binary) + 同目录一堆 .so / Python 库。
# 启动直接 exec 入口二进制，省掉 bootloader self-extract 阶段。
# electron-builder.json 的 extraResources 配置:
#   { from: "../dist/nexus-backend", to: "nexus-backend" }
# onedir 模式下整个目录被复制到 Nexus.app/Contents/Resources/nexus-backend/。
# paths.ts:48 会自动优先 onedir 入口检测（onedirExec），所以 desktop 启动逻辑不用改。
"$ROOT_DIR/.venv/bin/pyinstaller" \
  --name nexus-backend \
  --onedir \
  --paths "$ROOT_DIR" \
  "$ROOT_DIR/nexus/backend/run.py"
