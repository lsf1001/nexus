#!/usr/bin/env bash
#
# Nexus 卸载脚本
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/install.sh) --uninstall
# 或
#   curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/uninstall.sh | bash
#

set -e

NEXUS_HOME="${NEXUS_HOME:-$HOME/.nexus}"

echo "▸ 卸载 Nexus..."

# 删除主目录
if [ -d "$NEXUS_HOME" ]; then
  rm -rf "$NEXUS_HOME"
  echo "✓ 已删除 $NEXUS_HOME"
else
  echo "○ $NEXUS_HOME 不存在，跳过"
fi

# 删除符号链接
if [ -L "$HOME/.local/bin/nexus" ]; then
  rm -f "$HOME/.local/bin/nexus"
  echo "✓ 已删除 ~/.local/bin/nexus"
else
  echo "○ ~/.local/bin/nexus 不存在，跳过"
fi

echo ""
echo "✓ Nexus 卸载完成"
echo ""
echo "如需重新安装："
echo "  curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/install.sh | bash"