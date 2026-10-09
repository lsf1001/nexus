"""AppState frozen dataclass 单元测试。

WHY: spec §3.2 规定 5 字段 + frozen + MappingProxyType 防外部改。本测试
锁 4 个性质: frozen 不可改 / 字段访问 / MappingProxyType 不可变 / tuple 不可变。
"""

from __future__ import annotations

import asyncio
import time

import pytest


def test_app_state_is_frozen() -> None:
    """AppState 实例不可 mutate。"""
    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(),
        db_conn=None,
        started_at=time.time(),
    )

    with pytest.raises((AttributeError, Exception)) as exc_info:
        state.main_loop = None  # type: ignore[misc]
    assert "frozen" in str(exc_info.value).lower() or "cannot assign" in str(exc_info.value).lower()


def test_app_state_fields_accessible() -> None:
    """5 个字段可正常读。"""
    from nexus.backend.app_state import AppState

    loop = asyncio.new_event_loop()
    state = AppState(
        main_loop=loop,
        agents={"a1": object()},
        mcp_tools=(1, 2, 3),
        db_conn=object(),
        started_at=1.23,
    )
    assert state.main_loop is loop
    # MappingProxyType 也支持 __contains__,用 in 验证成员访问
    assert "a1" in state.agents
    assert state.mcp_tools == (1, 2, 3)
    assert state.started_at == 1.23


def test_app_state_agents_is_mapping_proxy() -> None:
    """agents 字段是 MappingProxyType,不可改。"""
    from types import MappingProxyType

    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(),
        db_conn=None,
        started_at=0.0,
    )
    assert isinstance(state.agents, MappingProxyType)
    with pytest.raises(TypeError):
        state.agents["new"] = object()  # type: ignore[index]


def test_app_state_mcp_tools_is_tuple() -> None:
    """mcp_tools 是 tuple,不可 append。"""
    from nexus.backend.app_state import AppState

    state = AppState(
        main_loop=asyncio.new_event_loop(),
        agents={},
        mcp_tools=(1, 2),
        db_conn=None,
        started_at=0.0,
    )
    assert isinstance(state.mcp_tools, tuple)
    with pytest.raises(AttributeError):
        state.mcp_tools.append(3)  # type: ignore[attr-defined]
