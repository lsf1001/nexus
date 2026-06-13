"""微信通道全局状态（账号 / 会话 / token / channel + 锁）。

从 wechat.py 拆分（2026-06-13 P0 重构）。所有跨函数的可变状态集中在此，
避免分散在业务模块里。

注意：模块级 dict/锁在 import 时创建，跨进程不共享。生产部署走单进程。
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .wechat_types import QRSession, WeChatChannel, WeixinAccount
else:
    QRSession = None  # type: ignore[assignment,misc]
    WeChatChannel = None  # type: ignore[assignment,misc]
    WeixinAccount = None  # type: ignore[assignment,misc]


# 账号与会话存储（带线程锁保护）
_active_logins: dict = {}  # session_key -> QRSession
_accounts: dict = {}  # account_id -> WeixinAccount
_context_tokens: dict = {}  # account_id:user_id -> context_token
_global_lock = threading.RLock()
_active_channel: object | None = None  # 当前活跃的微信通道（运行时是 WeChatChannel）


def get_active_wechat_channel() -> object:
    """获取当前活跃的微信通道实例。"""
    return _active_channel


def _set_active_channel(channel: object) -> None:
    """设置当前活跃的微信通道实例。"""
    global _active_channel
    _active_channel = channel


def _clear_active_channel() -> None:
    """清除当前活跃的微信通道实例（用户切换/退出时调用）。"""
    global _active_channel
    _active_channel = None
