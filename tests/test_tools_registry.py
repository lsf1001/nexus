"""TOOLS 列表不应包含 langchain_community 文件管理工具(由 FilesystemMiddleware 接管)。

WHY 2026-07-14:
- 此前 nexus TOOLS 只有 ``get_current_date``(YYYY-MM-DD),用户问
  "现在几点"LLM 只能回"我无法直接获取当前时间"。加 ``get_current_time``
  走 ``SHANGHAI_TZ``(与 fact_check.today 一致),让 LLM 直接回答时分。
"""

import re as _re

from nexus.backend.tools import TOOLS


def test_tools_no_legacy_file_management() -> None:
    """Nexus TOOLS 不应再含 deepagents FilesystemMiddleware 同名工具。

    deepagents 实际工具名(以 FilesystemMiddleware 为准):
    ``ls / read_file / glob / grep / write_file / edit_file``。
    此前 langchain_community 的 ``file_management.DeleteFileTool`` 等已被删除;
    本测试**正面对接 deepagents 工具集**,防止未来误回滚或重复实现。
    """
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    deepagents_fs_tools = {"ls", "read_file", "glob", "grep", "write_file", "edit_file"}
    overlap = names & deepagents_fs_tools
    assert not overlap, f"Nexus TOOLS 不应重名 deepagents 文件工具(由 FilesystemMiddleware 接管): {overlap}"


def test_tools_keeps_ask_user_and_date() -> None:
    """澄清工具和日期工具保留。"""
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "ask_user" in names
    assert "get_current_date" in names


def test_tools_includes_get_current_time() -> None:
    """``get_current_time`` 必须在 TOOLS 里,让 LLM 可答'现在几点'。

    WHY:用户期望问"现在几点了" → LLM 直接输出时分秒,而不是"我无法获取"。
    工具必须显式注册,否则 langchain agent 不会暴露给 LLM。
    """
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "get_current_time" in names, (
        f"TOOLS 必须包含 get_current_time(YYYY-MM-DD HH:MM:SS),当前列表: {sorted(names)}"
    )


def test_tools_includes_shell_run() -> None:
    """``shell_run`` 必须在 TOOLS 里(2026-07-14 加),让 LLM 可申请执行命令。

    配合 :class:`ShellHITLMiddleware` 使用:工具本体负责沙箱短路 + subprocess
    执行 + 审计写入,HITL 弹窗由中间件触发。

    若未来产品决定下架 shell 能力,改 ``TOOLS`` 列表即可,本测试会失败提醒。
    """
    names = {t.name for t in TOOLS if hasattr(t, "name")}
    assert "shell_run" in names, (
        f"TOOLS 必须包含 shell_run(HITL 守卫 + 沙箱校验的 shell 执行工具),当前列表: {sorted(names)}"
    )


def test_get_current_time_default_timezone_is_shanghai() -> None:
    """``get_current_time`` 默认时区必须是 Asia/Shanghai(项目事实源)。"""

    from nexus.backend.tools import get_current_time

    result = get_current_time.invoke({})
    # YYYY-MM-DD HH:MM:SS 24h 格式;regex 兼容 seconds 为任意 2 位
    assert _re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result), (
        f"get_current_time 必须返回 'YYYY-MM-DD HH:MM:SS' 格式,实际: {result!r}"
    )


def test_get_current_time_custom_timezone_respected() -> None:
    """``get_current_time(tz='UTC')`` 返回 UTC 时区的时间。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from nexus.backend.tools import get_current_time

    result = get_current_time.invoke({"tz": "UTC"})
    parsed = datetime.strptime(result, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    # 同一时刻(±2s)UTC 与本机时间的差应当反映 Shanghai(UTC+8)偏移;本测试只
    # 断言"返回值确实是 UTC 时刻"——通过解析出的 dt 是 UTC aware datetime。
    assert parsed.tzinfo is not None
    assert parsed.tzinfo.key == "UTC"


def test_get_current_time_signature_exposes_optional_tz() -> None:
    """LLM tool calling schema 必须带可选 tz 参数;不能是只接受一个位置参数。"""
    from nexus.backend.tools import get_current_time

    schema = get_current_time.args
    # langchain 0.3+/Pydantic v2:args 直接是 dict(OpenAI tool 风格)。
    # 支持 pydantic v1 风格 ``__fields__`` 兜底(可能 agent 装老版 langchain)。
    if isinstance(schema, dict):
        assert "tz" in schema, f"get_current_time schema 必须含 'tz' 字段,实际: {schema}"
        tz_field = schema["tz"]
        # Union[string, null](optional) 是 langchain 生成 Optional[tz] 的标准形态
        any_of = tz_field.get("anyOf") if isinstance(tz_field, dict) else None
        assert any_of is not None, f"tz 字段必须有 anyOf (Optional 类型),实际: {tz_field}"
    else:  # pragma: no cover - 兼容老 langchain
        fields = getattr(schema, "__fields__", None)
        assert fields is not None and "tz" in fields, (
            f"get_current_time 必须暴露 tz 参数供 LLM 选时区,实际 schema: {schema}"
        )
