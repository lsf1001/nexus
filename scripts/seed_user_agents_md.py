"""幂等初始化用户级 AGENTS.md。

WHY: deepagents :class:`MemoryMiddleware` 在 ``memory=[...]`` 列出但文件
不存在时,会跳过而不是报错。但空文件 vs 完全不存在差别巨大 ——
完全不存在时 MemoryMiddleware 没东西可注入,LLM 失去身份感。
此脚本保证首次启动后用户级 AGENTS.md 存在且包含 header 注释 + 空 section。

幂等:文件存在时不覆盖,直接退出 0。

用法:
    python scripts/seed_user_agents_md.py
"""

from __future__ import annotations

import sys
from pathlib import Path

USER_AGENTS_MD = Path.home() / ".deepagents" / "AGENTS.md"

INITIAL_CONTENT = """<!-- managed by deepagents MemoryMiddleware. 用户/agent 可自由编辑。 -->

# Nexus 用户偏好

<!-- 由 deepagents LLM 自动维护 -->

"""


def main() -> int:
    """若用户级 AGENTS.md 不存在,创建并写入初始模板。"""
    if USER_AGENTS_MD.exists():
        print(f"[seed] 已存在,跳过: {USER_AGENTS_MD}")
        return 0
    USER_AGENTS_MD.parent.mkdir(parents=True, exist_ok=True)
    USER_AGENTS_MD.write_text(INITIAL_CONTENT, encoding="utf-8")
    print(f"[seed] 创建: {USER_AGENTS_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
