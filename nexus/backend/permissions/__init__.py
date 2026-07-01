"""集中定义 FilesystemPermission 规则与受保护路径解析。

WHY: 把安全策略从 agent.py 抽出,便于审计 + 单测 + 后续扩展(MCP / execute
等场景复用同一判定函数)。

设计原则(2026-06-29 重构)
--------------------------
**只做白名单**,HITL 与质量门交给专门中间件。

历史实现含 ``mode="interrupt"`` 规则试图拦截 AGENTS.md 写入 / 项目源码
写入。但 deepagents 0.5.3 的 :class:`FilesystemPermission.mode` 只支持
``Literal["allow", "deny"]``(**没有** ``"interrupt"`` mode),``_check_fs_permission``
看到非法 mode 静默 fall-through(``return rule.mode`` 返回 "interrupt"
字符串但比较 ``== "deny"`` 不命中,落到默认 allow)。结果是所有
``mode="interrupt"`` 规则被框架忽略,HITL 路径默认放行 — E2E 2026-06-29
``test_e2e_interrupt_source`` 等 5 个场景全部 FAIL 的根因。

HITL 现在由 :class:`nexus.backend.middleware.hitl.PathAwareHITLMiddleware`
在 ``wrap_tool_call`` 阶段路径白名单判定后触发;AGENTS.md 的忠实度评估
由 :class:`nexus.backend.quality.middleware.QualityGateMiddleware` 接管。
本模块只剩两层白名单:
  - ``read /**`` allow:LLM 可读任何文件
  - ``write {project_root}/.nexus/**`` allow:产出物 / 配置 / 日志 / state
"""

from __future__ import annotations

from pathlib import Path

from deepagents.middleware.filesystem import FilesystemPermission


def build_default_permissions(project_root: Path) -> list[FilesystemPermission]:
    """构造默认 FilesystemPermission 规则列表(纯白名单)。

    Args:
        project_root: Nexus 项目根目录,用于展开 ``{project_root}`` 占位符。

    Returns:
        :class:`FilesystemPermission` 列表,直接传给 ``create_deep_agent(permissions=...)``。

    Note:
        - 读操作 ``["read"]`` 对全路径 allow(``/**``),LLM 可读任何文件。
        - 写白名单只覆盖 ``{project_root}/.nexus/**``,LLM 直接放行;
          其它路径(包括项目源码 / /tmp / AGENTS.md)走 deepagents 默认
          allow,但会被 :class:`PathAwareHITLMiddleware` /
          :class:`QualityGateMiddleware` 在更上层拦截。
        - ``FilesystemPermission`` 路径必须以 ``/`` 开头(框架硬约束),
          且不能含 ``..`` 或 ``~``(``__post_init__`` 校验)。
    """
    # 入口先 resolve,避免 macOS 上 /tmp -> /private/tmp 这类 symlink
    # 导致 build_default_permissions 拼的路径与 PathAwareHITLMiddleware
    # / QualityGateMiddleware 解析后的字符串不一致。
    project_root = project_root.expanduser().resolve()
    rules: list[FilesystemPermission] = [
        # 读:全开(LLM 看得到才能理解项目)
        FilesystemPermission(
            operations=["read"],
            paths=["/**"],
            mode="allow",
        ),
        # 写白名单:.nexus(配置 / 日志 / outputs / state / skills)
        # 必须以 '/' 开头(框架硬约束),使用绝对路径
        FilesystemPermission(
            operations=["write"],
            paths=[
                f"{project_root}/.nexus/**",
            ],
            mode="allow",
        ),
    ]
    return rules


def resolve_protected_paths(project_root: Path) -> list[Path]:
    """解析所有受保护的 AGENTS.md 路径为绝对路径。

    Returns:
        单元素绝对路径列表(``~/.nexus/AGENTS.md``),供
        :class:`QualityGateMiddleware` 校验 edit_file/write_file 目标路径
        是否需要走忠实度评估。

    Note:
        历史实现含 ``{project_root}/.nexus/AGENTS.md`` 与
        ``{project_root}/nexus/.deepagents/AGENTS.md`` 两条 ——
        2026-06 OpenClaw 定位重设计后产品身份 hardcode 进代码,
        这两个 dev 时路径已无对应文件,删除。
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
