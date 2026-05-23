from typing import Any
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from .config import CONFIG


def get_llm() -> ChatOpenAI:
    """创建 MiniMax 配置的 ChatOpenAI 实例。"""
    return ChatOpenAI(
        model="MiniMax-M2.7",
        openai_api_key=CONFIG["minimax_api_key"],
        openai_api_base=CONFIG["minimax_api_base"],
        temperature=0.7,
    )


def create_agent() -> Any:
    """创建带工具的 DeepAgents 智能体。"""
    from nexus.backend.tools import TOOLS

    return create_deep_agent(
        model=get_llm(),
        tools=TOOLS,
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