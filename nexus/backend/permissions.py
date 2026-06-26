"""集中定义 FilesystemPermission 规则与 HITL 触发判定。

WHY: 把安全策略从 agent.py 抽出,便于审计 + 单测 + 后续扩展(MCP / execute
等场景复用同一判定函数)。

设计原则:
  - 框架默认 ``allow``,所以**白名单路径显式 allow,其他路径隐式 allow**
    → 这条不变,因为 FilesystemPermission 没有 deny-by-default 语义。
  - 真正的高敏保护靠 ``interrupt`` 模式:用户在前端弹窗确认才放行。
  - 不引入 deny 规则(避免和 interrupt 语义重复 + 阻断 LLM 看到错误)。

HITL 触发面:
  - AGENTS.md 写入(覆盖 deepagents MemoryMiddleware 的全权)
  - 项目内非 .nexus/ 路径的写(防 LLM 改 nexus/ frontend/ desktop/ 源码)
"""

from __future__ import annotations

from pathlib import Path

from deepagents.middleware.filesystem import FilesystemPermission


def build_default_permissions(project_root: Path) -> list[FilesystemPermission]:
    """构造默认 FilesystemPermission 规则列表。

    Args:
        project_root: Nexus 项目根目录,用于展开 ``{project_root}`` 占位符。

    Returns:
        :class:`FilesystemPermission` 列表,直接传给 ``create_deep_agent(permissions=...)``。

    Note:
        - 读操作 ``["read"]`` 对全路径 allow(`/**`),LLM 可读任何文件。
        - 写操作分两层:.nexus/ 和 /tmp/ 直接 allow;AGENTS.md 必须 interrupt;
          其他路径(deepagents 框架对未匹配路径默认 allow)由同模块
          :func:`build_interrupt_on_for_agent` 提供的 ``when`` 谓词兜底
          (白名单内放行,其他路径触发 HITL)。
    """
    # 入口先 resolve,避免 macOS 上 /tmp -> /private/tmp 这类 symlink
    # 导致 build_default_permissions 拼的路径与 resolve_protected_paths
    # .resolve() 后的字符串不一致。
    project_root = project_root.expanduser().resolve()
    rules: list[FilesystemPermission] = [
        # 读:全开(LLM 看得到才能理解项目)
        FilesystemPermission(
            operations=["read"],
            paths=["/**"],
            mode="allow",
        ),
        # /tmp/ 只读:LLM 可以看临时文件,但不允许写入(产出物落 .nexus/)
        FilesystemPermission(
            operations=["read"],
            paths=["/tmp/**"],
            mode="allow",
        ),
        # 写白名单:.nexus(配置 / 日志 / outputs / state)
        # 必须以 '/' 开头(框架硬约束),使用绝对路径
        FilesystemPermission(
            operations=["write"],
            paths=[
                f"{project_root}/.nexus/**",
            ],
            mode="allow",
        ),
        # AGENTS.md 写入必须 HITL
        # 注:FilesystemPermission 路径必须以 '/' 开头,所以 ~ 要展开成绝对路径。
        # Nexus 是个人智能助理（对标 OpenClaw），用户数据目录唯一
        # ``~/.nexus/``，没有"项目级 AGENTS.md"概念 —— 只保护用户级那一条。
        FilesystemPermission(
            operations=["write"],
            paths=[
                str((Path.home() / ".nexus" / "AGENTS.md").expanduser().resolve()),
            ],
            mode="interrupt",
        ),
    ]
    return rules


def resolve_protected_paths(project_root: Path) -> list[Path]:
    """解析所有受保护的 AGENTS.md 路径为绝对路径。

    Returns:
        单元素绝对路径列表（``~/.nexus/AGENTS.md``）,供
        :class:`QualityGateMiddleware` 校验 edit_file/write_file 目标路径
        是否需要走忠实度评估。

    Note:
        历史实现含 ``{project_root}/.nexus/AGENTS.md`` 与
        ``{project_root}/nexus/.deepagents/AGENTS.md`` 两条 —— 2026-06
        OpenClaw 定位重设计后产品身份 hardcode 进代码,这两个 dev 时
        路径已无对应文件,删除。
    """
    return [(Path.home() / ".nexus" / "AGENTS.md").expanduser().resolve()]


def is_write_to_protected_path(
    *,
    tool_name: str,
    target_path: str,
    protected_paths: list[Path],
) -> bool:
    """判定一次工具调用是否命中受保护路径。

    Args:
        tool_name: 工具名(目前仅 ``write_file`` / ``edit_file`` 需要判定)。
        target_path: 工具入参里的目标文件路径(可能是绝对路径或相对路径)。
        protected_paths: :func:`resolve_protected_paths` 的结果。

    Returns:
        True 表示此次写入需要走 HITL 或质量门。
    """
    if tool_name not in {"write_file", "edit_file"}:
        return False
    try:
        resolved = Path(target_path).expanduser().resolve()
    except (OSError, RuntimeError):
        return False
    return any(resolved == p for p in protected_paths)
