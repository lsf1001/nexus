"""回归测试:MCP 加载失败时 logger 必须带 exc_info=True 记录完整堆栈。

WHY: 旧实现只 ``logger.warning("...: %s", e)``,没有 ``exc_info=True``,
生产事故排查看不到 traceback,只看到一行 message。python_project.md §1.6
明确要求 "错误日志含异常信息和关键业务上下文"。
"""

from __future__ import annotations

import logging
from concurrent.futures import Future

from nexus.backend import main


def test_mcp_load_failure_logs_exc_info(monkeypatch, caplog) -> None:
    """MCP load 抛异常时,logger.warning 必须带 exc_info=True。

    验证方式:直接 patch ``main._main_loop`` 和 ``asyncio.run_coroutine_threadsafe``
    触发 except 分支,断言 caplog 中日志记录的 exc_info 字段非空(由
    ``logging`` 模块自动填充,只要 ``exc_info=True`` 传入)。
    """

    def _boom(*args, **kwargs) -> Future:
        fut: Future = Future()
        fut.set_exception(RuntimeError("MCP 后端连接拒绝"))
        return fut

    monkeypatch.setattr(main, "_main_loop", object())
    monkeypatch.setattr(main, "_mcp_tools", None)
    monkeypatch.setattr("asyncio.run_coroutine_threadsafe", _boom)
    # conftest autouse 强制 NEXUS_ENABLE_MCP=false;这里把它打开触发 MCP load 分支
    monkeypatch.setenv("NEXUS_ENABLE_MCP", "true")
    # MCP 失败后 _create_agent_with_model 仍会被调用,这里 stub 掉避免触发真实模型构造
    monkeypatch.setattr(main, "_create_agent_with_model", lambda mcp_tools=None: None)

    with caplog.at_level(logging.WARNING, logger="nexus.backend.main"):
        main._ensure_agent_ready(app=object())

    # 找到 MCP 加载失败的日志记录
    records = [r for r in caplog.records if "MCP 加载失败" in r.message]
    assert len(records) >= 1, f"未找到 MCP 加载失败的日志: {[r.message for r in caplog.records]}"
    rec = records[0]
    assert rec.exc_info is not None, "logger.warning 必须传 exc_info=True,生产事故排查需要完整 traceback"
    # 验证 traceback 内容确实包含原始异常
    assert rec.exc_info[0] is RuntimeError
    assert "MCP 后端连接拒绝" in str(rec.exc_info[1])
