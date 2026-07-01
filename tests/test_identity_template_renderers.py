"""identity/directives.py 模板渲染器回归测试。

WHY: FACT 块 + FINAL REMINDER 累积 4 commit 贴片(2026-06-29 ~ 2026-07-01),
字符串内容难追。模板化后,这些测试锁定关键内容存在 + 关键变量被正确替换。"""

from __future__ import annotations

from unittest.mock import patch

from nexus.backend.identity.directives import (
    DIRECTIVES,
    render_fact_block,
    render_final_reminder,
)


def test_render_fact_block_substitutes_driver() -> None:
    out = render_fact_block("test-driver", "TestVendor")
    assert "test-driver" in out
    assert "TestVendor" in out


def test_render_fact_block_contains_blacklist_from_directives() -> None:
    """FACT 块必须包含 DIRECTIVES.training_bias_blacklist 所有项。"""
    out = render_fact_block("d", "v")
    for entry in DIRECTIVES.training_bias_blacklist:
        assert entry in out, f"blacklist 条目 {entry!r} 未出现在 FACT 块"


def test_render_fact_block_contains_identity_keywords() -> None:
    """FACT 块必须包含 DIRECTIVES 身份关键词(用于触发 LLM 走规则)。"""
    out = render_fact_block("d", "v")
    for kw in DIRECTIVES.identity_keywords_zh:
        assert kw in out, f"ZH 关键词 {kw!r} 未出现在 FACT 块"


def test_render_fact_block_contains_get_model_info_tool_call() -> None:
    """FACT 块必须强制 LLM 先调 get_model_info 工具。"""
    out = render_fact_block("d", "v")
    assert "get_model_info" in out


def test_render_final_reminder_substitutes_driver() -> None:
    out = render_final_reminder("test-driver", "TestVendor")
    assert "test-driver" in out
    assert "TestVendor" in out


def test_render_final_reminder_contains_blacklist_from_directives() -> None:
    out = render_final_reminder("d", "v")
    for entry in DIRECTIVES.training_bias_blacklist:
        assert entry in out, f"blacklist 条目 {entry!r} 未出现在 FINAL REMINDER"


def test_render_fact_block_with_empty_blacklist_renders_meaningful_text() -> None:
    """空 blacklist 时 FACT 块不能出现「」 / "" 等零宽 pattern。

    WHY:review (2026-07-01) 发现 ``_banned_examples_text()`` 在 blacklist 为空时
    返回 ``""``,被 template 替换进「以「{banned_examples}」开头」这种短语后变成
    「以「」开头」—— 零宽禁止前缀,语法不通,LLM 容易把这种"看起来像 prompt injection"
    的空角括号当作系统级漏洞信号。本测试守住空 blacklist 时输出必须是合法中文。
    """
    from nexus.backend.identity import directives

    empty_directives = type(directives.DIRECTIVES)(
        identity_keywords_zh=tuple(DIRECTIVES.identity_keywords_zh),
        identity_keywords_en=tuple(DIRECTIVES.identity_keywords_en),
        training_bias_blacklist=frozenset(),
    )
    with patch.object(directives, "DIRECTIVES", empty_directives):
        out = render_fact_block("d", "v")

    # 渲染后必须仍然是非空字符串
    assert isinstance(out, str)
    assert out.strip() != "", "空 blacklist 时 FACT 块仍必须输出非空内容"

    # 关键禁忌 pattern 不能出现
    assert "「」" not in out, f"空 blacklist 不能渲染出零宽角括号「」(空占位符泄漏),实参片段: {out[200:400]!r}"
    assert '""' not in out, f"空 blacklist 不能渲染出空双引号(英文空占位符泄漏),实参片段: {out[200:400]!r}"
    # 角括号里只有空格的 pattern(变体)也不能出现
    assert "「 " not in out and " 」" not in out, "空角括号带空格的变体也不能出现"


def test_render_final_reminder_with_empty_blacklist_renders_meaningful_text() -> None:
    """``render_final_reminder`` 在空 blacklist 时也不能渲染出「」"" 等零宽 pattern。

    WHY:之前 ``render_final_reminder`` 内联拼接 ``" / ".join(sorted(blacklist))``,
    空时直接产 ``""`` 串,被 template 替换进「"{banned_examples}"」后变成
    「""等任何默认值」—— 中文语法无意义且具 prompt-injection 嫌疑。
    修复后 ``render_final_reminder`` 与 ``render_fact_block`` 共用同一条空兜底路径。
    """
    from nexus.backend.identity import directives

    empty_directives = type(directives.DIRECTIVES)(
        identity_keywords_zh=tuple(DIRECTIVES.identity_keywords_zh),
        identity_keywords_en=tuple(DIRECTIVES.identity_keywords_en),
        training_bias_blacklist=frozenset(),
    )
    with patch.object(directives, "DIRECTIVES", empty_directives):
        out = render_final_reminder("d", "v")

    assert isinstance(out, str)
    assert out.strip() != ""
    assert "「」" not in out
    assert '""' not in out


def test_bad_examples_count_le_blacklist_count() -> None:
    """反例条目数应 <= blacklist 条目数(教学子集关系)。

    WHY:``_bad_examples_text`` 的反例硬编码 (``("Agnes-2.0-Flash", "Sapiens AI")`` 等)
    是 few-shot 教学子集,刻意窄于 ``DIRECTIVES.training_bias_blacklist`` 黑名单全集。
    反例条目数 > blacklist 是配置漂移信号(新增 blacklist 项没同步反例 / 反例删多了)。
    """
    from nexus.backend.identity.directives import _bad_examples_text

    blacklist_count = len(DIRECTIVES.training_bias_blacklist)
    rendered = _bad_examples_text()
    # 反例每行一条,行数 = 反例条目数(空字符串也算一条)
    example_count = len(rendered.splitlines()) if rendered else 0
    assert example_count <= blacklist_count, (
        f"bad_examples ({example_count}) > blacklist ({blacklist_count}); few-shot 反例不应多于 blacklist 黑名单条目"
    )


def test_dynamic_identity_build_fact_block_calls_renderer() -> None:
    """``_build_fact_block`` 必须调 ``render_fact_block``(行为契约而非源码扫描)。

    WHY review:旧版用 ``inspect.getsource`` 断言函数体含 ``render_fact_block``
    字符串,在重命名 / 注释遗留下会假阳性 / 假阴性。本测试改为 mock 行为契约:
    调 mock 替换 ``render_fact_block``,断言 (1) ``_build_fact_block`` 内部一定
    调了它,(2) 参数 ``(driver_name, driver_vendor)`` 传递正确,(3) 返回值透传。
    """
    from nexus.backend.middleware import dynamic_identity

    with patch.object(dynamic_identity, "render_fact_block", return_value="<FACT>") as m:
        result = dynamic_identity._build_fact_block("driver-x", "vendor-y")

    m.assert_called_once_with("driver-x", "vendor-y")
    assert result == "<FACT>"


def test_dynamic_identity_build_final_reminder_calls_renderer() -> None:
    """``_build_final_reminder`` 必须调 ``render_final_reminder``(行为契约)。"""
    from nexus.backend.middleware import dynamic_identity

    with patch.object(dynamic_identity, "render_final_reminder", return_value="<REM>") as m:
        result = dynamic_identity._build_final_reminder("driver-x", "vendor-y")

    m.assert_called_once_with("driver-x", "vendor-y")
    assert result == "<REM>"


def test_dynamic_identity_resolve_driver_none_falls_back() -> None:
    """``_resolve_driver(None)`` 兜底("未配置模型"/"未知厂商")。

    WHY:audit 2026-07-01 抽 ``_resolve_driver`` 后,``info=None`` 兜底
    ("未配置模型"/"未知厂商") 集中到本函数。中间层 ``_build_fact_block`` /
    ``_build_final_reminder`` 改签名为 ``(driver_name, driver_vendor)`` 后,
    None 兜底测试入口只剩一处 —— 本测试守住该集中点行为契约。
    """
    from nexus.backend.middleware import dynamic_identity

    assert dynamic_identity._resolve_driver(None) == ("未配置模型", "未知厂商")


def test_dynamic_identity_resolve_driver_empty_dict_falls_back() -> None:
    """``_resolve_driver({})`` 同样走兜底 — info dict 存在但缺 ``name``。"""
    from nexus.backend.middleware import dynamic_identity

    assert dynamic_identity._resolve_driver({}) == ("未配置模型", "未知厂商")
    assert dynamic_identity._resolve_driver({"name": "", "vendor": "x"}) == (
        "未配置模型",
        "未知厂商",
    )


def test_dynamic_identity_resolve_driver_normal() -> None:
    """正常 ``info`` 透传 ``name`` / ``vendor``。"""
    from nexus.backend.middleware import dynamic_identity

    assert dynamic_identity._resolve_driver({"name": "abc", "vendor": "v1"}) == ("abc", "v1")


def test_dynamic_identity_resolve_driver_missing_vendor() -> None:
    """``info.name`` 存在但 ``info.vendor`` 缺失时 vendor 兜底"未知厂商"。"""
    from nexus.backend.middleware import dynamic_identity

    assert dynamic_identity._resolve_driver({"name": "abc"}) == ("abc", "未知厂商")
