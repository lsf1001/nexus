#!/usr/bin/env bash
# 打包 Nexus 桌面 APP (.app + .dmg),产物 macOS arm64。
#
# 步骤:
#   1. 跑 build_sidecar.sh 生成 sidecar
#   2. cargo tauri build 产出 .app(Tauri 2 的 AppleScript-based DMG 在非交互 shell 必挂,
#      跳过它,自己用 hdiutil 打 DMG)
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

# 2. cargo tauri build(tauri.conf.json 的 targets=["app"],只产 .app 不打 DMG)
echo ">>> step 2: cargo tauri build..."
cd "$ROOT_DIR/desktop/src-tauri"
cargo tauri build --target "${ARCH}-apple-darwin"

# 3. 找 .app 产物
APP_BUNDLE="$ROOT_DIR/desktop/src-tauri/target/${ARCH}-apple-darwin/release/bundle/macos/${APP_NAME}.app"

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: app bundle not found at $APP_BUNDLE"
  exit 1
fi

# 4. 移到 release/(统一位置)
mkdir -p "$ROOT_DIR/release"
rm -rf "$ROOT_DIR/release/${APP_NAME}.app" 2>/dev/null || true
cp -R "$APP_BUNDLE" "$ROOT_DIR/release/${APP_NAME}.app"

# 5. 用 hdiutil 打 DMG(避开 tauri 2 的 AppleScript,后者在非交互 shell 必挂)
echo ">>> step 3: create DMG with hdiutil..."
DMG_OUT="$ROOT_DIR/release/${DMG_NAME}.dmg"
rm -f "$DMG_OUT"
rm -f /tmp/rw.*.dmg 2>/dev/null || true

# 在 .app 旁边建个临时目录(让 hdiutil 看到源)
TMP_STAGE="$(mktemp -d)"
cp -R "$APP_BUNDLE" "$TMP_STAGE/"

hdiutil create -volname "${APP_NAME}" \
  -srcfolder "$TMP_STAGE" \
  -ov -format UDZO \
  "$DMG_OUT"

rm -rf "$TMP_STAGE"

echo ">>> DMG: $DMG_OUT"
ls -lh "$DMG_OUT"

echo ">>> release/ 内容:"
ls -la "$ROOT_DIR/release/"
echo ">>> 提示: 把 release/${DMG_NAME}.dmg 分发给用户,用户拖到 /Applications 安装"