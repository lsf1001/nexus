"""Agent-level middleware (deepagents compatible).

子包包含挂接到 deepagents 0.6.x ``wrap_model_call`` / ``wrap_tool_call``
钩子的中间件。与 :mod:`nexus.backend.middleware`(路径感知 HITL 等更宽
口径中间件)并行存在,本子包按 plan 集中放置"对 LLM 输出 / 工具调用做内容
审查"类中间件(fact_check / 未来 quality 类),保持单一职责与文件大小
不超 800 行。
"""
