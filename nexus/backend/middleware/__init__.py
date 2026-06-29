"""Nexus 自定义 AgentMiddleware 集合。

WHY 这个包存在:
  LangChain ``create_agent`` 接收 ``middleware=[...]`` 列表,每个 middleware
  可以拦截 / 改写 ``wrap_model_call`` 钩子。Nexus 用这个钩子把"产品层"、
  "模型层"、安全层 等横切关注点插到 LLM 调用链上,既不动 LangChain
  框架代码、也不依赖 deepagents 内部 API。

设计原则:
  - middleware 之间**互不耦合**:每个 middleware 独立可测,``nexus.backend.agent``
    只负责把它们按顺序拼到 ``create_deep_agent(middleware=...)`` 里。
  - middleware 拿不到 graph state,只能改 ``ModelRequest``(model / system_message
    / messages / tools)然后调 ``handler(request)`` 透传。
  - **性能**:`wrap_model_call` 在每次 LLM 调用前都跑,middleware 内部应该
    是 O(1) 操作(读文件 / 调缓存)。不能跑 LLM 自身,会循环。
"""
