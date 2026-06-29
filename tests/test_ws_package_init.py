"""ws 包 ``__init__.py`` 公共符号 re-export 不变量测试。

WHY 存在
--------
2026-06-30 commit ``13113f7 refactor(ws): api/ws.py 1386 行拆 6 模块``
拆包后,``nexus/backend/api/ws/__init__.py`` 漏 re-export ``add_message``,
导致 4 处 :func:`unittest.mock.patch` 调用 ``nexus.backend.api.ws.add_message``
时直接 ``AttributeError``,6 个 E2E / 单元测试 FAIL。

本测试守住 ``__all__`` 列出的所有符号都可在 ``nexus.backend.api.ws.X``
找到,防止以后再发生"拆包漏 re-export"或"重构删除公共 API 没同步测试"的
问题。
"""

from __future__ import annotations

from nexus.backend.api import ws as ws_module


def test_ws_module_exposes_all_documented_symbols() -> None:
    """``__all__`` 列出的每个符号都能在 ws 模块上 attribute 找到。"""
    # __all__ 不一定存在(模块可以选择性不导出),但当前 ws 包明确维护了一份
    if not hasattr(ws_module, "__all__"):
        return
    missing: list[str] = []
    for name in ws_module.__all__:
        if not hasattr(ws_module, name):
            missing.append(name)
    assert not missing, f"ws 包 __all__ 列了以下符号但模块找不到(拆包漏 re-export?): {missing}"


def test_ws_module_add_message_is_callable() -> None:
    """``add_message`` 必须可访问且可调用,否则 mock.patch 报错 + E2E fail。"""
    assert hasattr(ws_module, "add_message"), (
        'ws 包必须 re-export add_message — 4 处 mock.patch("nexus.backend.api.ws.add_message") 依赖它'
    )
    assert callable(ws_module.add_message), "ws.add_message 必须是函数,不能是普通值"


def test_ws_module_add_message_points_to_db_add_message() -> None:
    """``ws.add_message`` 与 ``db.add_message`` 必须是同一函数对象。

    WHY:测试用 ``patch(\"nexus.backend.db.add_message\")`` 替换 db 模块属性,
    finalize.py / streaming.py 改 ``import ...db as _db`` + ``_db.add_message(...)``
    的属性查找才能拦截。如果 ws.add_message 被错误地重新绑定成 wrapper,
    测试断言 ``mock_add_message.called`` 仍然 False。
    """
    from nexus.backend import db as db_module

    assert ws_module.add_message is db_module.add_message, (
        "ws.add_message 必须是 db.add_message 的 re-export,不允许包装或重定向"
    )


def test_ws_module_handle_websocket_callable() -> None:
    """主端点必须 re-export(被 main.py 引用)。"""
    assert hasattr(ws_module, "handle_websocket")
    assert callable(ws_module.handle_websocket)


def test_ws_module_require_token_callable() -> None:
    """REST 鉴权依赖必须 re-export(被 main.py 引用)。"""
    assert hasattr(ws_module, "require_token")
    assert callable(ws_module.require_token)
