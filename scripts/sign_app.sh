#!/usr/bin/env bash
# 用 ad-hoc 签名 + entitlements 给 Nexus.app 打完整签名。
#
# 必要性:
#   cargo tauri build 只给单个二进制做 linker-signed(adhoc 但不 seal resources),
#   macOS 启动时 webview 子进程抛 "The operation is insecure"。
#   用 codesign --force --deep --options runtime + entitlements 重签可消除。
#
# 局限:
#   ad-hoc 签名仍不被 spctl/Gatekeeper 信任(无 Apple Developer ID),
#   用户首次启动需要"右键 → 打开"绕过。正式分发见 docs/operations/signing.md。

set -euo pipefail

APP_PATH="${1:-/Applications/Nexus.app}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENTITLEMENTS="$ROOT_DIR/desktop/src-tauri/entitlements.plist"

if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: app not found at $APP_PATH"
  exit 1
fi
if [ ! -f "$ENTITLEMENTS" ]; then
  echo "ERROR: entitlements not found at $ENTITLEMENTS"
  exit 1
fi

echo ">>> signing $APP_PATH with entitlements..."
# 只签顶层 .app(不 --deep),内部 binary / WKWebView WebContent 的
# 沙盒 profile 由 Tauri 2 build 时写入,自己重签会破坏嵌套签名。
codesign --force \
  --options runtime \
  --entitlements "$ENTITLEMENTS" \
  --sign - \
  "$APP_PATH"

echo ">>> verifying top-level signature..."
codesign -dv "$APP_PATH" 2>&1 | head -8

echo ""
echo ">>> verifying all nested binaries..."
codesign --verify --deep --strict "$APP_PATH" 2>&1 | head -5