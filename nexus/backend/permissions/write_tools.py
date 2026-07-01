"""统一写工具判定表。

WHY 存在:
  历史上 :class:`QualityGateMiddleware`(quality/middleware.py)和
  :class:`PathAwareHITLMiddleware`(middleware/hitl.py)各持一份**字节级相同**的
  ``_FILE_TOOLS`` / ``_WRITE_TOOL_PATTERNS`` / ``_READ_ONLY_TOOLS`` 常量和
  ``_is_write_tool()`` 函数 —— 典型 copy-paste 反模式。新增/删除写工具名要
  改两个文件,极易漂移。本模块抽出来做 single source of truth:

    - ``FILE_TOOLS``:精确白名单,deepagents 0.6.x 暴露的写文件工具全集
    - ``WRITE_TOOL_PATTERNS``:子串黑名单兜底(写工具名含有这些子串即视
      为写操作,覆盖 deepagents 未来版本新增的别名工具)
    - ``READ_ONLY_TOOLS``:精确白名单,即使名称含 file/document 也不算写
    - ``is_write_tool()``:统一判定入口,优先级:FILE_TOOLS → (小写化后
      READ_ONLY_TOOLS 黑名单) → WRITE_TOOL_PATTERNS

新增/删除工具名只改本文件,两个消费者自动同步。
"""

from __future__ import annotations

# deepagents 0.6.x 暴露给 LLM 的写文件工具名集合。
# 主路径: edit_file / write_file (核心写工具, 必须评估)。
# 别名: create_file / apply_patch / patch_file / str_replace_editor / write_document。
FILE_TOOLS: frozenset[str] = frozenset(
    {
        "edit_file",
        "write_file",
        "create_file",
        "apply_patch",
        "patch_file",
        "str_replace_editor",
        "write_document",
    }
)

# 黑名单兜底模式: 工具名包含这些子串即视为写文件工具。
# WHY 子串而非正则:deepagents 工具名都是 snake_case,子串 ``in name``
# 已经覆盖 99% 场景;正则匹配是过度工程,而且要处理 ``.*`` 边界 case。
WRITE_TOOL_PATTERNS: tuple[str, ...] = (
    "write_",
    "edit_",
    "patch_",
    "apply_",
    "_file",
    "_document",
)

# 明确只读工具白名单 — 即使名称含 file/document 也不视为写。
# WHY 必须放在 WRITE_TOOL_PATTERNS 前面查:read_file 含 ``_file`` 子串,
# 不先排除会被误判为写工具。
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "ls",
        "glob",
        "grep",
        "internet_search",
    }
)


def is_write_tool(tool_name: str) -> bool:
    """判定工具名是否为写操作(可能影响 AGENTS.md 或触发 HITL 弹窗)。

    判定优先级(顺序敏感):
      1. 空名 → False(避免空字符串误命中 patterns)
      2. 精确匹配 ``FILE_TOOLS``(**大小写敏感**)→ True
      3. 小写化后命中 ``READ_ONLY_TOOLS`` → False(读工具优先于写模式)
      4. 任一 ``WRITE_TOOL_PATTERNS`` 子串命中(小写化后)→ True
      5. 都不命中 → False

    Note:
        ``FILE_TOOLS`` 是大小写敏感的(白名单只列了小写形式);大写工具名
        会落空走子串匹配 → 仍可能被判为写(例如 ``"EDIT_FILE"`` → True)。

    Args:
        tool_name: deepagents 工具名(LLM 调用 ToolMessage.name 字段)。

    Returns:
        ``True`` if write, ``False`` otherwise (read-only or unknown)。
    """
    if not tool_name:
        return False
    if tool_name in FILE_TOOLS:
        return True
    name = tool_name.lower()
    if name in READ_ONLY_TOOLS:
        return False
    return any(pattern in name for pattern in WRITE_TOOL_PATTERNS)


__all__ = [
    "FILE_TOOLS",
    "WRITE_TOOL_PATTERNS",
    "READ_ONLY_TOOLS",
    "is_write_tool",
]
