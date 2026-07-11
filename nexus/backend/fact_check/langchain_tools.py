"""LangChain 工具包装:把 mcp/date_utils.py + mcp/fact_verify.py 暴露给 deepagents。

设计目标:
- LLM 可主动调这些工具自我校验(尤其 verify_claims),不依赖 MCP stdio 协议
- 用 ``@tool`` 装饰器(mcp 包未安装);错误以自然语言返回而非抛异常,让 LLM
  看见 ToolMessage 错误即可改写
- 时区沿用 date_utils 的 Asia/Shanghai(项目事实源)

工具列表:
- today            当前日期(Asia/Shanghai)YYYY-MM-DD
- weekday_of       给定日期转中文星期
- next_n_days      接下来 N 天的日期 + 星期(JSON 列表)
- verify_claims    校验文本中的事实声明(JSON 结果)
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from nexus.backend.mcp.date_utils import next_n_days as _next_n_days_impl
from nexus.backend.mcp.date_utils import today as _today_impl
from nexus.backend.mcp.date_utils import weekday_of as _weekday_of_impl
from nexus.backend.mcp.fact_verify import verify_claims as _verify_claims_impl


@tool
def today() -> str:
    """返回今天的日期(Asia/Shanghai 时区),格式 YYYY-MM-DD。

    用法:用户问"明天是哪天""这周六几号"时先调今天,再算偏移;不要凭记忆猜日期。
    """
    return _today_impl()


@tool
def weekday_of(date_str: str) -> str:
    """把 YYYY-MM-DD 日期转中文星期(星期一/二/三/四/五/六/日)。

    Args:
        date_str: YYYY-MM-DD 格式日期。

    Returns:
        中文星期字符串;若日期格式无效,返回以 "错误:" 开头的自然语言说明。
    """
    try:
        return _weekday_of_impl(date_str)
    except ValueError as exc:
        return f"错误:{exc}"


@tool
def next_n_days(start_date: str, n: int) -> str:
    """从 ``start_date`` 起往后 n 天,返回 JSON 数组(每项含 date 与 weekday 字段)。

    Args:
        start_date: YYYY-MM-DD 起始日,**结果不含** start_date 本身,从 start_date+1 开始。
        n: 取 1-30 范围内的整数。

    Returns:
        JSON 字符串;若参数无效,返回以 "错误:" 开头的自然语言说明。
    """
    try:
        rows = _next_n_days_impl(start_date, n)
    except ValueError as exc:
        return f"错误:{exc}"
    return json.dumps(rows, ensure_ascii=False)


@tool
def verify_claims(text: str) -> str:
    """对 ``text`` 中的事实声明(日期/星期/数学/单位/汇率)做确定性校验,返回 JSON。

    工作方式:提取日期/星期/数学/单位/汇率类断言,逐条对照 fact_check pipeline,返回
    ``{ok, claims_total, conflicts_total, claims, conflicts}`` 结构。

    用法:**写回复前先调用本工具自检**,冲突 (ok=false) 时按 conflicts 字段修正。

    Args:
        text: LLM 拟发出的回复文本;可包含任意中文陈述,工具会抽取可校验的子句。

    Returns:
        JSON 字符串。即便参数正常也不会抛错 —— Pipeline 内部已兜底空字符串/无可校验
        内容的情况。
    """
    result = _verify_claims_impl(text)
    return json.dumps(result.to_dict(), ensure_ascii=False)


# 注册到 deepagents 的工具顺序:跟 function 定义顺序一致;
# today → weekday_of → next_n_days → verify_claims(LLM 优先见自校验工具)。
FACT_CHECK_TOOLS = [
    today,
    weekday_of,
    next_n_days,
    verify_claims,
]

__all__ = [
    "today",
    "weekday_of",
    "next_n_days",
    "verify_claims",
    "FACT_CHECK_TOOLS",
]
