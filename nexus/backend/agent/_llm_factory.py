"""LLM 工厂函数 + 主题研究模式判断。

模块化拆分后,本模块集中承载:

- :func:`get_llm` — 构造带韧性包装的 LLM 实例
- :func:`is_research_topic` — 简单 keyword-based 研究主题判断

WHY 单独成包:``get_llm`` 是 deepagents 主入口的最关键依赖,所有
chat / subagent / quality-gate 都从它取模型实例。集中放一个文件便于
未来切换 LLM provider(目前只支持 ChatOpenAI 兼容协议)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = __import__("logging").getLogger(__name__)


def get_llm(
    model_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    temperature: float | None = None,
    retry=None,
    fallback=None,
    fallback_policy=None,
    timeout=None,
) -> BaseChatModel:
    """根据参数构造带韧性包装的 LLM 实例(超时 / 重试 / 降级)。

    本函数与历史版本保持向后兼容:
      - 前 4 个参数(``model_name`` / ``api_key`` / ``api_base`` / ``temperature``)
        与旧签名一致;不传 resilience 相关参数时行为等价于原来的 ``ChatOpenAI(...)``,
        差别仅在于返回值是 :class:`ResilientRunnable` 包装——但通过 ``__getattr__``
        代理可让现有 deepagents / LangChain 调用方零感知。
      - ``retry`` / ``fallback`` / ``fallback_policy`` / ``timeout`` 都是可选的;
        未传时各自使用 :mod:`nexus.backend.llm.policies` 中的默认值。

    Args:
        model_name: 模型名称;未提供且未提供 ``api_key`` 时抛 ``ValueError``。
        api_key: 自定义模型的 API key;传入则使用 ``model_name``(默认 ``"gpt-4"``)。
        api_base: 自定义模型的 API base URL。
        temperature: 模型温度;为 ``None`` 时按渠道默认(自定义渠道 0.7,
            主渠道使用 ``CONFIG["temperature"]``)。
        retry: 重试策略;``None`` 表示默认 :class:`RetryPolicy`。
        fallback: 备用 ``ChatOpenAI`` 实例;``None`` 表示不启用降级。
        fallback_policy: 降级判定策略;``None`` 表示默认 :class:`FallbackPolicy`。
        timeout: 超时策略;``None`` 表示默认 :class:`TimeoutPolicy``。

    Returns:
        韧性 LLM 包装实例,暴露 ``ainvoke`` / ``astream``;其它未覆盖的
        LangChain Runnable 方法/字段通过 :meth:`ResilientRunnable.__getattr__`
        代理到底层 ``ChatOpenAI``。

    Raises:
        ValueError: 既无 ``model_name`` 也无 ``api_key``,无法决定模型来源。
    """
    from ..config import CONFIG

    sdk_timeout = getattr(timeout, "per_step", 30.0) if timeout is not None else 30.0

    if api_key:
        # 自定义模型路径:保持旧行为
        from langchain_openai import ChatOpenAI

        chat = ChatOpenAI(
            model=model_name or "gpt-4",
            openai_api_key=api_key,
            openai_api_base=api_base,
            temperature=temperature if temperature is not None else 0.7,
            timeout=sdk_timeout,
            max_retries=0,
        )
    elif not model_name:
        # 同时缺 model_name 与 api_key:保持旧行为,明确报错
        raise ValueError("model_name and api_key are both required")
    else:
        # 走 CONFIG 默认渠道
        from langchain_openai import ChatOpenAI

        chat = ChatOpenAI(
            model=model_name,
            openai_api_key=CONFIG["minimax_api_key"],
            openai_api_base=CONFIG["minimax_api_base"],
            temperature=temperature if temperature is not None else CONFIG["temperature"],
            timeout=sdk_timeout,
            max_retries=0,
        )

    from ..llm.wrapper import build_resilient_llm

    return build_resilient_llm(
        primary=chat,
        fallback=fallback,
        retry=retry,
        timeout=timeout,
        fallback_policy=fallback_policy,
    )


def is_research_topic(topic: str) -> bool:
    """判断主题是否需要研究模式。"""
    research_keywords = ["研究", "分析", "调查", "报告", "对比", "趋势", "原理", "机制", "技术", "方案"]
    simple_keywords = ["今天", "明天", "昨天", "几号", "星期几", "你好", "谢谢", "再见", "1+1", "天气"]

    topic_lower = topic.lower()

    for keyword in research_keywords:
        if keyword in topic_lower:
            return True

    for keyword in simple_keywords:
        if keyword in topic_lower:
            return len(topic) > 20

    return len(topic) > 20
