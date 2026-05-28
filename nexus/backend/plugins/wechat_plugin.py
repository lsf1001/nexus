"""WeChat Channel Plugin - 微信通道插件

基于 Nexus Plugin SDK 实现
参考 OpenClaw: openclaw/plugin-sdk/channel-core
"""

import asyncio
import base64
import json
import logging
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from . import (
    ChannelConfig,
    ChannelManifest,
    ChannelMessageAdapter,
    ChannelSecurity,
    ChannelStatus,
    DMPolicy,
    DefaultChannelSecurity,
    DefaultSessionGrammar,
    InMemorySessionManager,
    InboundMessage,
    MessageContent,
    MessageReceipt,
    MessageReceiptStatus,
    MessageType,
    OutboundMessage,
    SecurityResult,
    Sender,
    Session,
    SessionManager,
    TextOnlyAdapter,
    define_channel_plugin_entry,
)


logger = logging.getLogger(__name__)

# 常量
DEFAULT_LONG_POLL_TIMEOUT_MS = 35_000
DEFAULT_API_TIMEOUT_MS = 15_000
DEFAULT_CONFIG_TIMEOUT_MS = 10_000
FIXED_BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.4"
DEFAULT_ILINK_BOT_TYPE = "3"
QR_LONG_POLL_TIMEOUT_MS = 35_000


# ========== 账号管理 ==========

class WeixinAccount:
    """微信账号"""
    def __init__(
        self,
        account_id: str,
        user_id: str = "",
        token: str = "",
        base_url: str = "",
    ):
        self.account_id = account_id
        self.user_id = user_id
        self.token = token
        self.base_url = base_url or FIXED_BASE_URL


# ========== API 客户端 ==========

async def _api_post(
    base_url: str,
    path: str,
    body: dict,
    token: str,
    timeout_ms: int,
) -> dict:
    """POST 请求"""
    url = f"{base_url}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _api_get(
    base_url: str,
    path: str,
    token: str,
    timeout_ms: int,
) -> dict:
    """GET 请求"""
    url = f"{base_url}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _generate_client_id() -> str:
    """生成客户端 ID"""
    return "".join(random.choices("0123456789ABCDEF", k=16))


def _build_base_info() -> dict:
    return {
        "version": CHANNEL_VERSION,
        "client_id": _generate_client_id(),
        "timestamp": int(time.time() * 1000),
    }


# ========== 微信消息适配器 ==========

class WechatMessageAdapter(TextOnlyAdapter):
    """微信消息适配器"""

    async def send(self, message: OutboundMessage, account: WeixinAccount) -> MessageReceipt:
        """发送消息"""
        text = message.content.text
        to_user = message.to_user_id

        client_id = _generate_client_id()
        item_list = [{"type": 1, "text_item": {"text": text}}]
        body = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": item_list,
            },
            "base_info": _build_base_info(),
        }

        try:
            await _api_post(
                account.base_url or FIXED_BASE_URL,
                "/ilink/bot/sendmessage",
                body,
                account.token,
                DEFAULT_API_TIMEOUT_MS,
            )
            return MessageReceipt(
                message_id=client_id,
                status=MessageReceiptStatus.SENT,
            )
        except Exception as e:
            return MessageReceipt(
                message_id="",
                status=MessageReceiptStatus.FAILED,
                error=str(e),
            )


# ========== 微信通道插件 ==========

class WechatChannelPlugin:
    """微信通道插件

    实现 Nexus Plugin SDK 接口
    """

    def __init__(self):
        # 元数据
        self._manifest = ChannelManifest(
            id="wechat",
            name="WeChat",
            version="1.0.0",
            description="微信通道插件",
            channel=True,
            supports_dm=True,
            supports_media=True,
        )

        # 配置
        self._config: Optional[ChannelConfig] = None
        self._account: Optional[WeixinAccount] = None

        # 状态
        self._status = ChannelStatus.DISCONNECTED

        # 组件
        self._security = DefaultChannelSecurity()
        self._session_manager = InMemorySessionManager()
        self._message_adapter = WechatMessageAdapter()

        # 回调
        self._on_message_callback = None
        self._on_status_change_callback = None

    @property
    def channel_id(self) -> str:
        return "wechat"

    @property
    def channel_name(self) -> str:
        return "WeChat"

    @property
    def manifest(self) -> ChannelManifest:
        return self._manifest

    @property
    def status(self) -> ChannelStatus:
        return self._status

    async def initialize(self, config: ChannelConfig) -> None:
        """初始化"""
        self._config = config

        # 从配置加载账号
        account_id = config.settings.get("account_id", "")
        if account_id:
            self._account = self._load_account(account_id)

        logger.info(f"Wechat plugin initialized: {config.channel_id}")

    async def start(self) -> None:
        """启动"""
        self._set_status(ChannelStatus.CONNECTING)

    async def stop(self) -> None:
        """停止"""
        self._set_status(ChannelStatus.STOPPED)

    async def connect(self) -> None:
        """连接"""
        if not self._account:
            logger.error("No account configured")
            self._set_status(ChannelStatus.ERROR)
            return

        self._set_status(ChannelStatus.CONNECTED)
        logger.info("Wechat channel connected")

    async def disconnect(self) -> None:
        """断开"""
        self._set_status(ChannelStatus.DISCONNECTED)

    async def reconnect(self) -> None:
        """重连"""
        self._set_status(ChannelStatus.RECONNECTING)
        await self.disconnect()
        await self.connect()

    async def send(self, message: OutboundMessage) -> MessageReceipt:
        """发送消息"""
        if not self._account:
            return MessageReceipt(
                message_id="",
                status=MessageReceiptStatus.FAILED,
                error="No account configured",
            )

        return await self._message_adapter.send(message, self._account)

    # ========== 账号管理 ==========

    def _get_state_dir(self) -> Path:
        """获取状态目录"""
        state_dir = Path.home() / ".nexus" / "weixin"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir

    def _get_account_path(self, account_id: str) -> Path:
        return self._get_state_dir() / "accounts" / f"{account_id}.json"

    def _load_account(self, account_id: str) -> Optional[WeixinAccount]:
        """加载账号

        注意: Token 使用 base64 编码存储，非真正加密。
        生产环境应使用系统密钥管理或专门的密钥存储服务。
        """
        path = self._get_account_path(account_id)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            encoded_token = data.get("token", "")
            token = base64.b64decode(encoded_token.encode()).decode()

            return WeixinAccount(
                account_id=account_id,
                user_id=data.get("userId", ""),
                token=token,
                base_url=data.get("baseUrl", ""),
            )
        except Exception as e:
            logger.error(f"Failed to load account: {e}")
            return None

    def set_account(self, account: WeixinAccount) -> None:
        """设置账号"""
        self._account = account

    # ========== 二维码登录 ==========

    async def get_qrcode(self) -> dict:
        """获取登录二维码"""
        body = {
            "base_info": _build_base_info(),
            "qr_type": DEFAULT_ILINK_BOT_TYPE,
        }

        data = await _api_post(
            FIXED_BASE_URL,
            "/ilink/bot/getqrcode",
            body,
            "",
            DEFAULT_CONFIG_TIMEOUT_MS,
        )

        return {
            "qrcode": data.get("qrcode", ""),
            "qrcode_url": data.get("qrcode_img_content", ""),
            "session_key": str(uuid.uuid4()),
        }

    # ========== 回调 ==========

    def on_message(self, callback: Callable) -> None:
        """注册消息回调"""
        self._on_message_callback = callback

    def on_status_change(self, callback: Callable) -> None:
        """注册状态回调"""
        self._on_status_change_callback = callback

    def _set_status(self, status: ChannelStatus) -> None:
        if self._status != status:
            self._status = status
            if self._on_status_change_callback:
                self._on_status_change_callback(status)

    # ========== 安全 ==========

    async def check_security(self, sender_id: str, content: str) -> SecurityResult:
        """安全检查"""
        sender = Sender(sender_id=sender_id)
        return await self._security.check_sender(sender)


# ========== 工厂函数 ==========

@define_channel_plugin_entry(ChannelManifest(
    id="wechat",
    name="WeChat",
    version="1.0.0",
    description="微信通道插件",
    channel=True,
    supports_dm=True,
))
def create_wechat_channel() -> WechatChannelPlugin:
    """创建微信通道插件实例"""
    return WechatChannelPlugin()
