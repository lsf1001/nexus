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

# 加载 rust env(cargo/rustc 不在默认 PATH)
if [ -f "$HOME/.cargo/env" ]; then
  # shellcheck disable=SC1091
  . "$HOME/.cargo/env"
fi

VERSION="${VERSION:-1.1.0}"
ARCH="${ARCH:-$(uname -m)}"  # arm64 或 x86_64
APP_NAME="Nexus"
DMG_NAME="${APP_NAME}-${VERSION}-${ARCH}"

# 1. 打 sidecar
echo ">>> step 1: build sidecar..."
bash "$ROOT_DIR/scripts/build_sidecar.sh"

# 1b. 准备 build-time 随机 WS token(2026-07 pre-release hardening)
#     同一机器多次打 DMG 复用同一 token,重打不破坏老用户授权。
#     build.rs 通过 env BUILD_WS_TOKEN 拿 + 持久化到 desktop/src-tauri/.build_token
#     beforeBuildCommand 用 VITE_NEXUS_WS_TOKEN(env 注入) 给 Vite build 期 baked-in
TOKEN_FILE="$ROOT_DIR/desktop/src-tauri/.build_token"
if [ ! -f "$TOKEN_FILE" ]; then
  openssl rand -hex 32 > "$TOKEN_FILE"
  echo ">>> step 1b: generated WS token → $TOKEN_FILE"
fi
export VITE_NEXUS_WS_TOKEN="$(cat "$TOKEN_FILE")"
export BUILD_WS_TOKEN="$VITE_NEXUS_WS_TOKEN"

# 2. cargo tauri build(tauri.conf.json 的 targets=["app"],只产 .app 不打 DMG)
#    不传 --target:让 cargo 用 host default target,产物在 target/release/bundle/macos/
#    之前用 --target aarch64-apple-darwin 时 cargo 把 host default 写到了
#    target/release/ 而不是 target/aarch64-apple-darwin/release/,反而绕远了
echo ">>> step 2: cargo tauri build..."
cd "$ROOT_DIR/desktop/src-tauri"
cargo tauri build

# 3. 找 .app 产物
APP_BUNDLE="$ROOT_DIR/desktop/src-tauri/target/release/bundle/macos/${APP_NAME}.app"

if [ ! -d "$APP_BUNDLE" ]; then
  echo "ERROR: app bundle not found at $APP_BUNDLE"
  exit 1
fi

# 4. 移到 ~/Library/Caches/nexus/build/(Apple 约定的构建产物位置,
#    Spotlight 默认排除 ~/Library/Caches/,Launchpad 不扫描这个位置)
#    按 docs/operations/e2e-06-27.md 经验,放家目录根级 release/ 会被 Launchpad 当独立 app 显示
CACHE_DIR="$HOME/Library/Caches/nexus/build"
mkdir -p "$CACHE_DIR"
# 先 unregister 上一次的 build 产物,避免 lsregister 数据库留 stale 引用
LSREG=/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister
$LSREG -u "$CACHE_DIR/${APP_NAME}.app" 2>/dev/null || true
rm -rf "$CACHE_DIR/${APP_NAME}.app" 2>/dev/null || true
cp -R "$APP_BUNDLE" "$CACHE_DIR/${APP_NAME}.app"

# 4c. release/ 保留 .build/ 作为快速访问副本(Spotlight 排除)
RELEASE_BUILD="$ROOT_DIR/release/.build"
mkdir -p "$RELEASE_BUILD"
rm -rf "$RELEASE_BUILD/${APP_NAME}.app" 2>/dev/null || true
cp -R "$APP_BUNDLE" "$RELEASE_BUILD/${APP_NAME}.app"
# 加 never-index 属性(目录 + .app 都加),Spotlight 跳过整个子树
touch "$RELEASE_BUILD/.metadata_never_index"
xattr -w com.apple.metadata:com_apple_metadata_never_index true "$RELEASE_BUILD" 2>/dev/null || true
xattr -w com.apple.metadata:com_apple_metadata_never_index true "$RELEASE_BUILD/${APP_NAME}.app" 2>/dev/null || true

# 4b. 删 cargo tauri build 留在 target/ 里的 bundle,避免同样的 Launchpad 重复图标
#     target/ 在 .gitignore 里但 Spotlight/Launchpad 仍会索引
#     注意:必须放在 4c 之后,否则 release/.build 副本拿不到源
$LSREG -u "$APP_BUNDLE" 2>/dev/null || true
rm -rf "$APP_BUNDLE" 2>/dev/null || true

# 5. 在写入 DMG 前完成签名。签名必须发生在 staging copy 之前，否则
#    DMG 内仍是 cargo 产出的未 seal App，只有缓存副本被签名。
echo ">>> step 3: sign .app with entitlements..."
bash "$ROOT_DIR/scripts/sign_app.sh" "$CACHE_DIR/${APP_NAME}.app"

# 6. 用 hdiutil 打 DMG(避开 tauri 2 的 AppleScript,后者在非交互 shell 必挂)
echo ">>> step 4: create DMG with hdiutil..."
DMG_OUT="$ROOT_DIR/release/${DMG_NAME}.dmg"
rm -f "$DMG_OUT"
rm -f /tmp/rw.*.dmg 2>/dev/null || true

# 在 .app 旁边建个临时目录(让 hdiutil 看到源)
# 源用 CACHE_DIR 里的(4 步刚 copy 过去,没被删)
TMP_STAGE="$(mktemp -d)"
cp -R "$CACHE_DIR/${APP_NAME}.app" "$TMP_STAGE/"

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
