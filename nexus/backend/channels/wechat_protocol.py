"""微信通道协议层：客户端 ID / 头 / base_info / 版本号等纯函数。

从 wechat.py 拆分（2026-06-13 P0 重构）。本层无 IO、无状态，纯粹构建/计算。
"""

from __future__ import annotations

import base64
import random
import uuid

# 与 wechat.py 共享的常量
CHANNEL_VERSION = "2.4.4"


def _generate_client_id() -> str:
    """生成客户端消息 ID。"""
    return f"nexus-weixin-{uuid.uuid4().hex[:16]}"


def _random_wechat_uin() -> str:
    """生成随机 UIN (OpenClaw 兼容)。"""
    uint32 = random.getrandbits(32)
    return base64.b64encode(str(uint32).encode()).decode()


def _build_client_version(version: str) -> int:
    """构建客户端版本号 (OpenClaw 兼容)。

    uint32 encoded as 0x00MMNNPP
    High 8 bits fixed to 0; remaining bits: major<<16 | minor<<8 | patch.
    e.g. "1.0.11" -> 0x0001000B = 65547
    """
    parts = version.split(".")
    major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return ((major & 0xFF) << 16) | ((minor & 0xFF) << 8) | (patch & 0xFF)


def _build_headers(token: str | None = None) -> dict:
    """构建请求头 (OpenClaw 兼容)。"""
    headers = {
        "Content-Type": "application/json",
        "iLink-App-Id": "bot",
        "iLink-App-ClientVersion": str(_build_client_version(CHANNEL_VERSION)),
        "AuthorizationType": "ilink_bot_token",
        "X-WECHAT-UIN": _random_wechat_uin(),
    }
    if token and token.strip():
        headers["Authorization"] = f"Bearer {token.strip()}"
    return headers


def _build_base_info() -> dict:
    """构建 base_info (OpenClaw 兼容)。"""
    return {
        "channel_version": CHANNEL_VERSION,
        "bot_agent": "OpenClaw",
    }
