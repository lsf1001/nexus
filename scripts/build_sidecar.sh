#!/usr/bin/env bash
# 打 Python sidecar(PyInstaller onedir)
# 产物: release/nexus-runtime/ (整个目录)
# Tauri 的 externalBin 期望一个可执行文件,onedir 模式产物的可执行文件就在 nexus-runtime/nexus-runtime

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# 1. 构建前端(若未构建)
if [ ! -d "$ROOT_DIR/frontend/dist" ]; then
  echo ">>> building frontend..."
  (cd frontend && npm install && npm run build)
fi

# 2. PyInstaller onedir(无 webview 依赖)
echo ">>> pyinstaller onedir for sidecar..."
"$ROOT_DIR/.venv/bin/pip" install --quiet pyinstaller
rm -rf "$ROOT_DIR/release/nexus-runtime"
mkdir -p "$ROOT_DIR/release"

"$ROOT_DIR/.venv/bin/pyinstaller" \
  --name nexus-runtime \
  --onedir \
  --noconfirm \
  --paths "$ROOT_DIR" \
  --collect-submodules fastapi \
  --collect-submodules deepagents \
  --collect-submodules langchain \
  --collect-submodules mcp \
  --collect-submodules uvicorn \
  --hidden-import=uvicorn \
  --hidden-import=nexus.backend.main \
  "$ROOT_DIR/nexus/backend/runtime_main.py"

# 3. 移产物
mv "$ROOT_DIR/dist/nexus-runtime" "$ROOT_DIR/release/nexus-runtime"
rm -rf "$ROOT_DIR/dist" "$ROOT_DIR/build"

echo ">>> sidecar: $ROOT_DIR/release/nexus-runtime/"
ls -la "$ROOT_DIR/release/nexus-runtime/" | head -10

# 4. Tauri externalBin 命名约定: nexus-runtime-{rust_target_triple}
# 例如 aarch64-apple-darwin, x86_64-apple-darwin(不是 uname -m 的 arm64)
ARCH_RUST=$(rustc -vV 2>/dev/null | awk '/^host:/ {print $2}' | cut -d- -f1)
[ -z "$ARCH_RUST" ] && ARCH_RUST="aarch64"  # mac 默认 aarch64
PLATFORM="apple-darwin"
TARBALL_NAME="nexus-runtime-${ARCH_RUST}-${PLATFORM}"
cp "$ROOT_DIR/release/nexus-runtime/nexus-runtime" \
   "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"
chmod +x "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"

echo ">>> Tauri sidecar: $ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"
ls -lh "$ROOT_DIR/desktop/src-tauri/binaries/${TARBALL_NAME}"