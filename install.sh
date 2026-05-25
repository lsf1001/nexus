#!/usr/bin/env bash
# Nexus 安装脚本
#
# Usage:
#   curl -fsSL https://.../install.sh | bash
#
# 环境变量:
#   NEXUS_HOME    - 安装目录 (默认: ~/.nexus)
#   NEXUS_SKIP_PYTHON - 跳过 Python 检查
#   UV_BIN        - uv 二进制路径 (自动检测)

set -euo pipefail

# Colors
if [ -t 1 ] || [ "${FORCE_COLOR:-}" = "1" ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[0;33m'
  CYAN='\033[0;36m'
  BOLD='\033[1m'
  NC='\033[0m'
else
  RED='' GREEN='' YELLOW='' CYAN='' BOLD='' NC=''
fi

log_info()    { printf "${CYAN}▸${NC} %s\n" "$*"; }
log_success() { printf "${GREEN}✔${NC} %s\n" "$*"; }
log_warn()   { printf "${YELLOW}⚠${NC} %s\n" "$*" >&2; }
log_error()  { printf "${RED}✖${NC} %s\n" "$*" >&2; }

# Exit trap
cleanup() {
  local exit_code=$?
  if [ $exit_code -ne 0 ]; then
    echo "" >&2
    log_error "安装失败 (exit code ${exit_code})"
    log_error "请访问 https://github.com/... 获取帮助"
  fi
}
trap cleanup EXIT

# 检测 OS
detect_os() {
  case "$(uname -s)" in
    Darwin)  OS="macos" ;;
    Linux)   OS="linux" ;;
    *)       OS="unknown" ;;
  esac
}
detect_os

# 默认安装目录
NEXUS_HOME="${NEXUS_HOME:-$HOME/.nexus}"
export NEXUS_HOME

# 创建目录
mkdir -p "$NEXUS_HOME"

log_info "安装 Nexus 到 $NEXUS_HOME"

# ---------------------------------------------------------------------------
# 检查 Python
# ---------------------------------------------------------------------------
if [ "${NEXUS_SKIP_PYTHON:-}" != "1" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    log_error "Python 3 未安装"
    log_info "请安装 Python 3.11+: https://www.python.org/downloads/"
    exit 1
  fi

  PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
  log_success "Python $PYTHON_VERSION"
fi

# ---------------------------------------------------------------------------
# 安装 uv
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  log_info "安装 uv..."
  if ! curl -fsSL https://astral.sh/uv/install.sh | sh; then
    log_error "uv 安装失败"
    exit 1
  fi
  # 添加到 PATH
  export PATH="$HOME/.local/bin:$PATH"
fi
log_success "uv 已就绪"

# ---------------------------------------------------------------------------
# 安装依赖
# ---------------------------------------------------------------------------
log_info "安装 Nexus 依赖..."

# 创建虚拟环境
uv venv "$NEXUS_HOME/.venv"

# 安装依赖
uv pip install --python "$NEXUS_HOME/.venv/bin/python" \
  fastapi uvicorn[standard] \
  deepagents==0.5.3 \
  langchain-openai \
  langchain-community \
  duckduckgo-search \
  aiosqlite \
  pydantic \
  python-dotenv

log_success "依赖安装完成"

# ---------------------------------------------------------------------------
# 复制应用代码 (如果是从 Git 安装)
# ---------------------------------------------------------------------------
if [ -d "$(dirname "$0")/nexus" ]; then
  log_info "复制应用代码..."
  cp -r "$(dirname "$0")/nexus" "$NEXUS_HOME/nexus"
fi

# ---------------------------------------------------------------------------
# 创建配置文件
# ---------------------------------------------------------------------------
if [ ! -f "$NEXUS_HOME/models.json" ]; then
  log_info "创建默认配置..."
  cat > "$NEXUS_HOME/models.json" << 'EOF'
{
  "models": [
    {
      "id": "default",
      "name": "MiniMax-M2.7",
      "api_key": "",
      "api_base": "https://api.minimaxi.com/v1",
      "temperature": 0.7,
      "is_active": true
    }
  ]
}
EOF
fi

# ---------------------------------------------------------------------------
# 创建启动脚本
# ---------------------------------------------------------------------------
cat > "$NEXUS_HOME/nexus" << NEXUS_SCRIPT
#!/usr/bin/env bash
# Nexus 启动脚本

export NEXUS_HOME="$NEXUS_HOME"
export PATH="$NEXUS_HOME/.venv/bin:$PATH"
export PYTHONPATH="$NEXUS_HOME/nexus:\$PYTHONPATH"

cd "\$NEXUS_HOME/nexus"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
NEXUS_SCRIPT

chmod +x "$NEXUS_HOME/nexus"

# 创建符号链接到 ~/.local/bin
mkdir -p "$HOME/.local/bin"
ln -sf "$NEXUS_HOME/nexus" "$HOME/.local/bin/nexus"

log_success "安装完成!"
echo ""
echo "启动 Nexus: nexus"
echo "或直接运行: $NEXUS_HOME/nexus"
echo ""
echo "首次使用请设置 API Key:"
echo "export MiniMax_API_KEY='your-key'"
