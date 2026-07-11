"""测试把 fact-check 模块(date_utils + fact_verify)包成 LangChain @tool 暴露给 deepagents。

设计意图:
- LLM 写回复前可主动调 verify_claims 自检
- 工具用 @tool 装饰器(本项目未装 mcp 包,走 langchain @tool 不走 MCP stdio)
- 工具名称 = 函数名,description 必须是中文(LLM 看的就是中文)
"""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool

from nexus.backend.fact_check.langchain_tools import (
    FACT_CHECK_TOOLS,
    next_n_days,
    today,
    verify_claims,
    weekday_of,
)


class TestToolsAreBaseTool:
    def test_today_tool_is_base_tool(self) -> None:
        assert isinstance(today, BaseTool)

    def test_weekday_of_tool_is_base_tool(self) -> None:
        assert isinstance(weekday_of, BaseTool)

    def test_next_n_days_tool_is_base_tool(self) -> None:
        assert isinstance(next_n_days, BaseTool)

    def test_verify_claims_tool_is_base_tool(self) -> None:
        assert isinstance(verify_claims, BaseTool)


class TestToolsHaveNameAndDescription:
    """工具 name + description 是 LLM 看到的元数据;description 必须中文,缺一不可。"""

    def test_all_tools_have_chinese_description(self) -> None:
        for tool in (today, weekday_of, next_n_days, verify_claims):
            assert tool.description, f"{tool.name} missing description"
            # Chinese description: at least one CJK char
            assert any("一" <= c <= "鿿" for c in tool.description), (
                f"{tool.name} description not in Chinese: {tool.description!r}"
            )

    def test_tool_names_are_stable(self) -> None:
        assert today.name == "today"
        assert weekday_of.name == "weekday_of"
        assert next_n_days.name == "next_n_days"
        assert verify_claims.name == "verify_claims"


class TestToolInvocations:
    @pytest.mark.asyncio
    async def test_today_returns_string(self) -> None:
        from datetime import datetime

        from nexus.backend.mcp.date_utils import SHANGHAI_TZ

        result = await today.ainvoke({})
        # YYYY-MM-DD format matching Asia/Shanghai today
        expected = datetime.now(SHANGHAI_TZ).date().isoformat()
        assert result == expected

    @pytest.mark.asyncio
    async def test_weekday_of_returns_chinese(self) -> None:
        result = await weekday_of.ainvoke({"date_str": "2026-07-10"})
        assert result == "星期五"

    @pytest.mark.asyncio
    async def test_verify_claims_wrong_weekday(self) -> None:
        result = await verify_claims.ainvoke(
            {"text": "明天是2026年7月11日 星期五"},
        )
        # Result is JSON-serialized dict; checks substring for failure markers
        assert (
            "false" in result.lower() or "conflict" in result.lower() or '"ok": false' in result.lower()
        )

    @pytest.mark.asyncio
    async def test_verify_claims_correct(self) -> None:
        result = await verify_claims.ainvoke(
            {"text": "明天是2026年7月11日 星期六"},
        )
        assert '"ok": true' in result.lower() or "pass" in result.lower()


class TestFactCheckToolsList:
    def test_exports_list_with_four_tools(self) -> None:
        assert len(FACT_CHECK_TOOLS) == 4
        names = {t.name for t in FACT_CHECK_TOOLS}
        assert names == {"today", "weekday_of", "next_n_days", "verify_claims"}
