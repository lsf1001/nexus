#!/usr/bin/env bash
# 打包 Nexus 桌面 APP(.app + .dmg),产物 macOS arm64。
#
# 步骤:
#   1. PyInstaller onedir 打包 launcher.py → dist/nexus-backend/ (含完整 Python 运行时)
#   2. 把 frontend/dist/ 拷到 dist/nexus-backend/_internal/frontend/(launcher 通过 NEXUS_FRONTEND_DIST 找到)
#   3. 构造 Nexus.app bundle 结构:
#        Contents/Info.plist
#        Contents/MacOS/Nexus          (壳脚本,exec nexus-backend)
#        Contents/Resources/nexus-backend/  (PyInstaller 产物)
#   4. hdiutil 打 DMG
#
# 为什么不继续用 electron-builder:
#   - Electron + Python 双运行时,DMG 167MB,反主流(Ollama / Msty 单二进制)
#   - pywebview 走 macOS 原生 WKWebView,无 Chromium,APP 内只有一个二进制
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${VERSION:-1.0.0}"
ARCH="arm64"
APP_NAME="Nexus"
DMG_NAME="${APP_NAME}-${VERSION}-${ARCH}"

# 1. 前端构建(已是 dist/ 状态可跳过)
if [ ! -d "$ROOT_DIR/frontend/dist" ]; then
  echo ">>> building frontend..."
  (cd frontend && npm install && npm run build)
fi

# 2. 后端 PyInstaller 打包
echo ">>> pyinstaller onedir..."
"$ROOT_DIR/.venv/bin/pip" install --quiet pyinstaller
rm -rf "$ROOT_DIR/dist/nexus-backend" "$ROOT_DIR/release"
"$ROOT_DIR/.venv/bin/pyinstaller" \
  --name nexus-backend \
  --onedir \
  --noconfirm \
  --paths "$ROOT_DIR" \
  --collect-submodules webview \
  --collect-submodules bottle \
  --hidden-import=webview.platforms.cocoa \
  --hidden-import=objc \
  --hidden-import=WebKit \
  "$ROOT_DIR/nexus/backend/launcher.py"

# 3. 把前端 dist 拷进 PyInstaller _internal(让 launcher 找到)
INTERNAL_DIR="$ROOT_DIR/dist/nexus-backend/_internal"
if [ ! -d "$INTERNAL_DIR" ]; then
  # PyInstaller >=6.0: _internal 改名 _internal? 实际仍是 _internal 或同名
  INTERNAL_DIR="$ROOT_DIR/dist/nexus-backend"
fi
mkdir -p "$INTERNAL_DIR/frontend"
cp -R "$ROOT_DIR/frontend/dist/." "$INTERNAL_DIR/frontend/"
echo ">>> frontend dist copied to $INTERNAL_DIR/frontend"

# 4. 构造 .app bundle
APP_DIR="$ROOT_DIR/release/${APP_NAME}.app"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# PyInstaller onedir 整个目录挪到 Resources/
mv "$ROOT_DIR/dist/nexus-backend" "$APP_DIR/Contents/Resources/nexus-backend"

# Info.plist
cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
  <key>CFBundleExecutable</key><string>${APP_NAME}</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundleIdentifier</key><string>com.yexiaobai.nexus</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>${APP_NAME}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
PLIST

# 拷贝 icon.icns 到 Resources
if [ -f "$ROOT_DIR/dist/macos-assets/icon.icns" ]; then
  cp "$ROOT_DIR/dist/macos-assets/icon.icns" "$APP_DIR/Contents/Resources/icon.icns"
fi

# MacOS/Nexus 启动壳脚本:直接 exec PyInstaller 产物的主二进制
cat > "$APP_DIR/Contents/MacOS/${APP_NAME}" <<SH
#!/usr/bin/env bash
# Nexus.app 启动壳脚本 —— Finder 双击 APP 时由 LaunchServices 调用
# exec PyInstaller 打的单进程入口,所有逻辑(含后端 + WKWebView)都在那一个进程里
DIR="\$(cd "\$(dirname "\$0")/../Resources/nexus-backend" && pwd)"
exec "\$DIR/nexus-backend" "\$@"
SH
chmod +x "$APP_DIR/Contents/MacOS/${APP_NAME}"

echo ">>> .app built at $APP_DIR"

# 5. hdiutil 打 DMG
DMG_PATH="$ROOT_DIR/release/${DMG_NAME}.dmg"
rm -f "$DMG_PATH"

# 用 UDZO 压缩 + UDIF 格式(macOS 标准 DMG)
hdiutil create \
  -volname "${APP_NAME}" \
  -srcfolder "$APP_DIR" \
  -ov \
  -format UDZO \
  -imagekey zlib-level=9 \
  "$DMG_PATH"

echo ">>> DMG: $DMG_PATH"
ls -lh "$DMG_PATH"
du -sh "$APP_DIR"