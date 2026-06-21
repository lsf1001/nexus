"""wechat_state 活跃 channel 访问器测试（P0 step 7/7）。

get_active_wechat_channel / _set_active_channel / _clear_active_channel
从原 wechat.py 迁到 wechat_state.py，行为等价：模块级单例 + 显式 setter/clear。
"""

from __future__ import annotations


def test_active_channel_starts_none() -> None:
    """无 setter 时返回 None。"""
    from nexus.backend.channels import wechat_state

    # 隔离：避免与其它测试共享状态
    wechat_state._clear_active_channel()
    assert wechat_state.get_active_wechat_channel() is None


def test_set_and_get_active_channel() -> None:
    """set 后 getter 拿到同一对象。"""
    from nexus.backend.channels import wechat_state

    sentinel = object()
    try:
        wechat_state._set_active_channel(sentinel)
        assert wechat_state.get_active_wechat_channel() is sentinel
    finally:
        wechat_state._clear_active_channel()


def test_clear_active_channel() -> None:
    """clear 后回到 None。"""
    from nexus.backend.channels import wechat_state

    wechat_state._set_active_channel(object())
    assert wechat_state.get_active_wechat_channel() is not None
    wechat_state._clear_active_channel()
    assert wechat_state.get_active_wechat_channel() is None


def test_set_overwrites_previous() -> None:
    """重复 set 后只有最新值生效。"""
    from nexus.backend.channels import wechat_state

    a = object()
    b = object()
    try:
        wechat_state._set_active_channel(a)
        wechat_state._set_active_channel(b)
        assert wechat_state.get_active_wechat_channel() is b
        assert wechat_state.get_active_wechat_channel() is not a
    finally:
        wechat_state._clear_active_channel()


def test_re_exports_via_legacy_wechat_module() -> None:
    """旧 wechat.py 兼容路径仍能拉出这三个符号。"""
    from nexus.backend.channels.wechat import (  # noqa: F401
        _clear_active_channel,
        _set_active_channel,
        get_active_wechat_channel,
    )
