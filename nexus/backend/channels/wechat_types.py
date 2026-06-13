"""微信通道数据类型。

从 wechat.py 拆分（2026-06-13 P0 重构）。包含账号 / 会话 / 消息类型等 dataclass 与 enum。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# 与 wechat.py 共享的常量
FIXED_BASE_URL = "https://ilinkai.weixin.qq.com"


@dataclass
class WeixinAccount:
    """微信账号数据。"""

    account_id: str
    user_id: str
    token: str
    base_url: str = ""
    cdn_base_url: str = "https://novac2c.cdn.weixin.qq.com/c2c"


@dataclass
class QRSession:
    """二维码登录会话。"""

    session_key: str
    qrcode: str
    qrcode_url: str
    started_at: float = field(default_factory=time.time)
    status: str = "wait"
    bot_token: str | None = None
    ilink_bot_id: str | None = None
    ilink_user_id: str | None = None
    base_url: str = ""
    current_api_base_url: str = FIXED_BASE_URL
    pending_verify_code: str | None = None


# 消息类型常量（保留原 API 形态：class 形式，含同名属性）
class MessageItemType:
    """消息项类型。"""

    NONE = 0
    TEXT = 1
    IMAGE = 2
    VOICE = 3
    FILE = 4
    VIDEO = 5


class MessageTypeEnum:
    """消息类型枚举。"""

    NONE = 0
    USER = 1
    BOT = 2


class MessageState:
    """消息状态。"""

    NEW = 0
    GENERATING = 1
    FINISH = 2
