#!/usr/bin/env bash
# 打包 Nexus 桌面 APP (.app + .dmg),产物 macOS arm64。
#
# 步骤:
#   1. 跑 build_sidecar.sh 生成 sidecar
#   2. cargo tauri build 产出 .app + .dmg
#
# 为什么不继续用 PyInstaller:
#   - Tauri 主程序只 ~10 MB,sidecar 单独打 ~40 MB
#   - 不用打包 Python 解释器到主程序,启动快
#   - 关窗保活/Dock 重开走 Tauri 内置 API,无需 monkey-patch

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${VERSION:-1.1.0}"
ARCH="${ARCH:-$(uname -m)}"  # arm64 或 x86_64
APP_NAME="Nexus"
DMG_NAME="${APP_NAME}-${VERSION}-${ARCH}"

# 1. 打 sidecar
echo ">>> step 1: build sidecar..."
bash "$ROOT_DIR/scripts/build_sidecar.sh"

# 2. cargo tauri build
echo ">>> step 2: cargo tauri build..."
cd "$ROOT_DIR/desktop/src-tauri"
cargo tauri build --target "${ARCH}-apple-darwin"

# 3. 找产物
APP_BUNDLE="$ROOT_DIR/desktop/src-tauri/target/${ARCH}-apple-darwin/release/bundle/macos/${APP_NAME}.app"
DMG_SOURCE="$ROOT_DIR/desktop/src-tauri/target/${ARCH}-apple-darwin/release/bundle/dmg/${DMG_NAME}.dmg"

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: app bundle not found at $APP_BUNDLE"
  exit 1
fi

# 4. 移到 release/(统一位置)
mkdir -p "$ROOT_DIR/release"
rm -rf "$ROOT_DIR/release/${APP_NAME}.app" 2>/dev/null || true
cp -R "$APP_BUNDLE" "$ROOT_DIR/release/${APP_NAME}.app"

# 5. 复制 DMG(如果 cargo tauri build 已生成)
if [ -f "$DMG_SOURCE" ]; then
  cp "$DMG_SOURCE" "$ROOT_DIR/release/${DMG_NAME}.dmg"
  echo ">>> DMG: $ROOT_DIR/release/${DMG_NAME}.dmg"
  ls -lh "$ROOT_DIR/release/${DMG_NAME}.dmg"
fi

echo ">>> release/ 内容:"
ls -la "$ROOT_DIR/release/"
echo ">>> 提示: 把 release/${DMG_NAME}.dmg 分发给用户,用户拖到 /Applications 安装"